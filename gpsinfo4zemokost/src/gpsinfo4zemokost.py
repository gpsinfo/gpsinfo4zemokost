"""

 (c) 2019 Rechenraum e.U. (office@rechenraum.com)
 
 This file is part of gpsinfo (www.gpsinfo.org).

 gpsinfo is free software: you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation, either version 3 of the License, or
 (at your option) any later version.

 gpsinfo is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 GNU General Public License for more details.

 You should have received a copy of the GNU General Public License
 along with gpsinfo. If not, see <http://www.gnu.org/licenses/>.

 Author(s): Andreas Fuchs (andreas.fuchs@rechenraum.com)

"""


"""
This file contains the definition of the plugin class GpsInfoForZemokost
and the definitions of the various dialog classes.
"""
# Qt, qgis and osgeo modules
from PyQt5.QtCore import QSettings, QTranslator, qVersion, QCoreApplication
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import QAction
from PyQt5.Qt import QApplication
import qgis.core, qgis.gui
from osgeo import gdal, ogr, osr

# standard python modules
import os.path
import requests as r

# custom modules
from . import function_module as fm
from . import gpsinfo4zemokost_dialog as gps_info
from .resources import *

class GpsInfoForZemokost:

    def __init__(self, iface):
        """
        An instance of this class is created when the plugin is loaded by
        __init__.py. It receives a reference (iface) to the QGIS interface.
        """
        # Save this reference to the QGIS interface
        self.iface = iface

        """
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'AustrianMeanElevation_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)

            if qVersion() > '4.3.3':
                QCoreApplication.installTranslator(self.translator)

        # Declare instance attributes
        """
        self.actions = []
        self.menu = 'gpsinfo4zemokost'

        
    """
    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('AustrianMeanElevation', message)
    """

    def initGui(self):
        #Create a Qaction object for the pulgin,
        icon_path = ':/plugins/gpsinfo4zemokost/images/gpsinfo_logo_pink_24px.png'
        self.action = QAction(QIcon(icon_path), 'Durchschnittliche Hangneigung berechnen', 
                              self.iface.mainWindow())
        self.action.setObjectName('gpsInfoForZemokost')
        self.action.setWhatsThis('Durchschnittliche Hangneigung berechnen')
        self.action.setStatusTip('Durchschnittliche Hangneigung berechnen')
        
        # connect it to self.run method, defined below
        self.action.triggered.connect(self.run)
        

        # and add it to the toolbar and menu of the QGIS interface.
        self.iface.addToolBarIcon(self.action)        
        self.iface.addPluginToMenu('&gpsinfo4zemokost', self.action)

    def unload(self):
        # Removes the plugin menu item and icon from QGIS GUI.
        self.iface.removePluginMenu('&gpsinfo4zemokost', self.action)
        self.iface.removeToolBarIcon(self.action)


    def run(self):
        # do all the checks (EPSG, >0 polygon layers, >0 features, server connection)
        em = ''   # stores the error message. If empty, plugin may start.

        # load the nonempty polygon layers and their indices
        poly_dic, poly_ind = fm.load_layers(self.iface)

        # check if Qgis version is 3.x.x
        if int(qgis.core.Qgis.QGIS_VERSION[0]) < 3:
            em = ('Diese Erweiterung wird von ihrer Version von QGIS nicht unterstützt. '
                  'Bitte aktualisieren Sie auf die Version 3.4 oder höher.')
        # check if there is at least one polygon layer with at least one feature
        elif len(poly_ind) == 0:
            em = ('Sie müssen mindestens einen Polygonlayer '
                 'mit mindestens einem Polygon im Koordinatenreferenzsystem "EPSG:31287" erstellen.')
        # check server access
        else:
            try:
                r.get('https://austrian-geodata-services.org/')
                connection = True
            except r.exceptions.ConnectionError:
                connection = False
            if not connection:
                try:  # in this case, the problem is the gpsinfo-server
                    r.get('http://www.orf.at')
                    r.get('http://www.google.com)')
                    em = ('gpsinfo4zemokost kann keine Verbindung zum Server http://gpsinfo.org herstellen. '
                          'Bitte versuchen Sie es zu einem späteren Zeitpunkt erneut.')  
                except r.exceptions.ConnectionError: # in this case, the problem is user's internet connection
                    em = ('gpsinfo4zemokost kann keine Verbindung zum Server http://gpsinfo.org herstellen. '
                          'Bitte überprüfen Sie Ihre Internetverbindung.')
            else:    # also check whether we can access and unzip data from the server, here, tile (1,1)
                # number of rows of alternatively downloaded dataset

                if fm.gdal_downloader(1, 1) == None and fm.alt_downloader(1, 1) == None: # if gdal.Open does not work
                    em = ('gpsinfo4zemokost kann nicht auf die Daten auf dem Server http://gpsinfo.org zugreifen. '
                          'Bitte versuchen Sie es zu einem späteren Zeitpunkt erneut.')


        # now either start pluging or show error dialog
        if em == '':
            # show the main dialog / start the plugin
            self.dlg = gps_info.GpsInfo4ZemokostMainDlg(self.iface)
            self.dlg.update()
            width = 40  # this is approx. margin plus vertical header width
            for i in range(5):
                width += self.dlg.resultTable.columnWidth(i)
            self.dlg.setMinimumWidth(width)
            self.dlg.resize(width, self.dlg.size().height())

            self.dlg.show()
            # at this point, we leave this file and continue in gps_info_4_zemokost_dialog.py
            # through the functions connected to the various buttons of the dialog
        else:
            # print the error message
            self.errormessage = gps_info.GpsInfo4ZemokostErrorDlg()
            self.errormessage.message.setText(em)
            self.errormessage.adjustSize()
            self.errormessage.setMinimumSize(self.errormessage.size())
            self.errormessage.show()

