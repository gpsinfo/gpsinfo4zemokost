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

# Qt, qgis and osgeo modules
from PyQt5.QtCore import QSettings, QTranslator, qVersion, QCoreApplication, Qt
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import QAction, QDialog, QTableWidgetItem, QHeaderView, QFileDialog, QApplication, QWidget, QLabel
from PyQt5.Qt import QApplication
from PyQt5 import uic
import qgis.core, qgis.gui
from osgeo import gdal, ogr, osr

# standard python modules
import webbrowser
import os.path

# custom module
from . import function_module as fm


# This loads the .ui file so that PyQt can populate the plugin with the elements from Qt Designer
FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), '../ui/gpsinfo4zemokost_dialog.ui'))

class GpsInfo4ZemokostMainDlg(QDialog, FORM_CLASS):
    def __init__(self, iface, parent=None):
        super(GpsInfo4ZemokostMainDlg, self).__init__(parent)
    
        # setup the geometry of the dialog
        self.setupUi(self)

        # didn't seem to work in Linux, but probably in Windows
        self.setWindowIcon(QIcon(':/plugins/gpsinfo4zemokost/images/gpsinfo_logo_pink_24px.png'))

        # set icon for "Abfrage starten" button
        try:
            self.run.setIcon(QIcon(':/plugins/gpsinfo4zemokost/images/check_icon.png'))
        except:
            pass
        
        # get the list of polygon layers. At this point, we know that it's nonempty.
        self.poly_dic, self.poly_ind = fm.load_layers(iface)

        # populate the layer selection combobox
        self.fill_combobox(iface)
        # update to enable/disable "only selected features" checkbox
        # at this point, we already know that there is at least 1 non-empty polygon layer
        self.update()

        # setup progress bar such that it shows 0%
        self.progressBar.setMinimum(0)
        self.progressBar.setMaximum(10)  # some number different from 0
        self.progressBar.setTextVisible(True)
        self.setProgressValue(0)

        # disable save button
        self.saveButton.setEnabled(False)

        # setup the header of the result table
        self.resultTable.setColumnCount(4)
        self.resultTable.setRowCount(0)
        self.resultTable.setEnabled(False)
        self.resultTable.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode(0))
        # ResizeMode(0) means resizeable by user
        self.resultTable.setHorizontalHeaderItem(1, QTableWidgetItem('Polygonschwerpunkt [(m, m)]'))
        self.resultTable.setHorizontalHeaderItem(2, QTableWidgetItem(u'Fläche [km\u00b2]'))
        self.resultTable.setHorizontalHeaderItem(3, QTableWidgetItem('Hangneigung [1]'))

        # connect the buttons to functions
        self.closeButton.clicked.connect(self.reject)
        self.run.clicked.connect(self.start_preprocess)
        self.selectLayer.currentIndexChanged.connect(self.update)     
        self.onlySelFeat.stateChanged.connect(self.clear_result)
        self.saveButton.clicked.connect(self.save_result)
        self.about_dlg = GpsInfo4ZemokostAbout()
        self.aboutButton.clicked.connect(self.about_dlg.show)
        self.helpButton.clicked.connect(self.openHelp)
        self.rasterBrowse.clicked.connect(self.getRasterFilename)
        self.rasterCheck.stateChanged.connect(self.enableSaveRaster)

        # instantiate clipboard for copy and paste purpose
        self.clip = QApplication.clipboard()

    def setProgressValue(self, val):
        pb = self.progressBar
        pb.setValue(val)
        percentage = (pb.value() - pb.minimum()) / (pb.maximum() - pb.minimum()) * 100
        if pb.maximum() - pb.minimum() < 100:
            self.progressBar.setFormat('{}% der Daten heruntergeladen'.format(int(percentage)))
        else:
            self.progressBar.setFormat('{:.1f}% der Daten heruntergeladen'.format(percentage))


    def openHelp(self):     # connected to help button
        # loc_help_file = os.path.join(os.path.dirname(__file__), '../doc/manual.html')
        try: 
            webbrowser.open('http://gpsinfo.org/gpsinfo4zemokost/')   
        except:
            pass

    def enableSaveRaster(self, state):
        self.rasterBrowse.setEnabled(state)
        self.rasterFilePath.setEnabled(state)
        self.clear_result()

    def fill_combobox(self, iface):     # called at startup by __init__
        # Clear the combobox
        self.selectLayer.clear() 

        # Get a polygon icon
        poly_icon = qgis.core.QgsLayoutItemPolygon(qgis.core.QgsLayout(qgis.core.QgsProject.instance())).icon()

        # populate the combobox
        for l in self.poly_dic:
            combo_item_name = self.poly_dic[l].name()
            self.selectLayer.insertItem(self.poly_ind.index(l), 
                                        poly_icon, combo_item_name)

        try:
            # if there is an active layer and it is a polygon layer, make it the current selection
            active_id = iface.activeLayer().id()
            if active_id in self.poly_dic:
                self.selectLayer.setCurrentIndex(self.poly_ind.index(active_id))
        except:
            pass

        # set attribute to currently selected layer
        self.selected_layer = self.poly_dic[self.poly_ind[self.selectLayer.currentIndex()]]

    def getRasterFilename(self):
        # open a file browser
        (file_path, filt) = QFileDialog.getSaveFileName(self, directory = os.getenv('HOME'), 
                                                        caption = 'Rasterdaten speichern', 
                                                        filter = 'ESRI-Grid (*.asc)')

        if file_path != '':  # if user pressed cancel, file_path is still empty
            # check whether the user entered file extension '.asc'. If not, add it
            (direc, fname) = os.path.split(file_path)
            if len(fname.rpartition('.asc')[2]) != 0:
                fname = fname + '.asc'
                self.rasterFilePath.setText(os.path.join(direc, fname))
            else:
                self.rasterFilePath.setText(file_path)



    def clear_result(self):     # this is smaller sister of update(). Connected to state change of checkbox
        self.setProgressValue(0)
        # clear the result table
        self.resultTable.setRowCount(0)
        self.resultTable.setEnabled(False)
        self.saveButton.setEnabled(False)


    def update(self):      # Connected to state change of combobox

        # get the layer selected in the menu. We know it is non-empty
        self.selected_layer = self.poly_dic[self.poly_ind[self.selectLayer.currentIndex()]]

        # check if there are selected features
        selected_feature_available = bool(self.selected_layer.selectedFeatureCount())

        # enable/disable and check/uncheck checkbox accordingly
        self.onlySelFeat.setEnabled(selected_feature_available)
        self.onlySelFeat.setChecked(selected_feature_available)

        # clear the result view
        self.clear_result()

        # set the remaining table column name and adjust number of rows
        first_field = self.selected_layer.fields()[0].name()
        self.resultTable.setHorizontalHeaderItem(0, QTableWidgetItem(first_field))
        self.resultTable.resizeColumnsToContents()


    def start_preprocess(self):   # Connected to Start button. Checks the size of the selected features and
        # displays a warning, when they are bigger than 200 square-km. If warning is ignored or not needed,
        # method self.start_preprocess is called.
        

        # get a feature iterator containing the (selected) features in the selected layer
        only_sel = self.onlySelFeat.isChecked()
        if self.onlySelFeat.isChecked():
            feats = list(self.selected_layer.getSelectedFeatures())
        else:
            feats = list(self.selected_layer.getFeatures())

        # calculate covered area
        area = 0
        for f in feats:
            area += f.geometry().area() / 1000000
        
        if area > 200:
            # The data on server takes about 120 kb / square-km.
            warning = (u'Die ausgewählten Features sind {:.0f} km\u00b2 groß. Für die Berechnung '
                       'müssen ungefähr {:.0f} Megabyte an Daten heruntergeladen werden. ').format(area, area * 0.12)
            if self.rasterFilePath.text() != '':
                # in order to check how the big the raster file will be, we create a vector layer
                # containing the features and compute its bounding box
                l = qgis.core.QgsVectorLayer("Polygon?crs=epsg:31287", "selected_feature_layer", "memory")
                l.dataProvider().addFeatures(feats)
                # trim the extent of the layer
                l.updateExtents()
                ext = l.extent()
                bdbox_area = (ext.xMaximum() - ext.xMinimum()) * (ext.yMaximum() - ext.yMinimum()) / 1000000
                # an ESRI-Grid File occupies about 8.657244 MB per square-km
                warning += ('Die gespeicherten Rasterdaten werden ungefähr {:.0f} Megabyte'
                            ' an Platz in Anspruch nehmen. ').format(bdbox_area * 0.2667)

            warning += 'Dies kann einige Zeit in Anspruch nehmen.'
            self.size_warn_dlg = GpsInfo4ZemokostSizeWarningDlg(self)
            self.size_warn_dlg.warning.setText(warning)
            self.size_warn_dlg.adjustSize()
            self.size_warn_dlg.show()       
            # the accept signal of size_warn_dlg is connected to start_process
        else:
            self.start_process()
       

    def start_process(self):       #Basically calls fm.process, which calls fm.clipped_raster,
        # found in function_module.py. Those two functions do the main processing and return a (hopefully empty) warning message.


        # first clear the result, just in case it hasn't happened.
        self.clear_result()

        # now do the processing and possibly get a warning message
        warning = fm.process(self)
        if warning != '':
            if warning.count('\n\n') == 1:
                warning += '\nDer Grund kann sein, dass das Feature außerhalb Österreichs liegt.'
            else:
                warning += '\nDer Grund kann sein, dass die Features außerhalb Österreichs liegen.'
            self.warn_dlg = GpsInfo4ZemokostWarningDlg()
            self.warn_dlg.warning.setText(warning)
            self.warn_dlg.adjustSize()
            #self.warn_dlg.setMinimumSize(self.size())
            self.warn_dlg.show()
    
    def keyPressEvent(self, event):     # override the key press event to define keyboard shortcuts

        # (1) Copying to clipboard: event should be C-Key pressed while Control-Key is pressed
        # check if something was pressed before the event & Control is now pressed. This was found in 
        # https://stackoverflow.com/questions/24971305/copy-pyqt-table-selection-including-column-and-row-headers
        if event.modifiers() & Qt.ControlModifier:
            if event.key() == Qt.Key_C: 
                s = self.result_to_csv(True) 
                self.clip.setText(s)
 
        # (2) Save as: event should be S-Key pressed while Control-Key is pressed. (As above)
        if self.saveButton.isEnabled() and event.modifiers() == Qt.ControlModifier:
            if event.key() == Qt.Key_S: 
                self.save_result()

        # (3) Close on escape
        if not event.modifiers() and event.key() == Qt.Key_Escape:
           self.reject()

        # (4) run on enter
        if not event.modifiers() and event.key() in [Qt.Key_Return, Qt.Key_Enter]:
           self.start_process()

        # (5) Open help on F1
        if not event.modifiers() and event.key() == Qt.Key_F1:
           self.openHelp()


    def result_to_csv(self, selected):    # transforms (selected) content of result table to .csv string
        # this method is called by "save_result()" and when Ctrl-C is pressed (see keyPressEvent())

        sep = ';'    # a separator for values.
        s = ''       # here we store the .csv

        # create lists of row and column values of selected cells
        ind_r = []   # will hold the row values of all (selected) cells
        ind_c = []   # will hold the column values of all (selected) cells
        if selected:
            ind_list = self.resultTable.selectedIndexes()
            for i in ind_list:
                ind_r.append(i.row())
                ind_c.append(i.column())
        else:
            for ir in range(self.resultTable.rowCount()):
                for ic in range(self.resultTable.columnCount()):
                    ind_r.append(ir)
                    ind_c.append(ic)

        # check if the (selected) cells cover a rectangular region
        if len(ind_r) != 0 and len(ind_r) == (max(ind_r)+1-min(ind_r)) * (max(ind_c)+1-min(ind_c)):
            # arrange cell texts to a ; delimited text and copy to clipboard
            # first save the header = column names
            for ic in range(min(ind_c), max(ind_c) + 1):
                t = self.resultTable.horizontalHeaderItem(ic).text()
                if ic == 1: # this column is the centroid. We extract the x- and y-coordinates separately
                    s +=  'Polygonschwerpunkt X [m]' + sep + 'Polygonschwerpunkt Y [m]' + sep
                else:
                    s +=  self.resultTable.horizontalHeaderItem(ic).text() + sep
            s += '\n'
            # now add the selected cell contents
            for ir in range(min(ind_r), max(ind_r) + 1):
                for ic in range(min(ind_c), max(ind_c) + 1):
                    if ic == 1: # this column is the centroid. We extract the x- and y-coordinates separately
                        try:
                            xy = self.resultTable.item(ir, ic).text().partition(',')
                            x = xy[0].partition('(')[2]
                            y = xy[2].partition(')')[0]
                            s += x + sep + y + sep
                        except AttributeError: # for empty fields, just in case
                            s += ' ' + sep + ' ' + sep
                    else:
                        try:
                            s += self.resultTable.item(ir, ic).text() + sep
                        except AttributeError: # for empty fields, just in case
                            s += ' ' + sep

                s = s.rstrip(sep)
                s += '\n'
            s = s.rstrip('\n')
        return s


    def save_result(self):     # connected to save button
        # get the result as csv-string
        s = self.result_to_csv(False)
        # open a file selection dialog
        (path, filt) = QFileDialog.getSaveFileName(self, directory = os.getenv('HOME'), 
                                                   caption = 'Ergebnis speichern', 
                                                   filter = 'CSV-Datei (*.csv);; Alle Dateien (*)', 
                                                   initialFilter = 'CSV-Datei (*.csv)')
        if path != '':
            (direc, fname) = os.path.split(path)
            # check if the user entered '.csv'-extension in case the CSV filter is selected
            if filt == 'CSV-Datei (*.csv)' and fname.rpartition('.csv')[2] != '':
                path = path + '.csv'
            f = open(path, 'w') 
            f.write(s)
            f.close()


#########################################
# create the dialog for the error message
FORM_CLASS_ERR_DLG, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), '../ui/error_dialog.ui'))

class GpsInfo4ZemokostErrorDlg(QDialog, FORM_CLASS_ERR_DLG):
    def __init__(self, parent=None):
        """Constructor."""
        super(GpsInfo4ZemokostErrorDlg, self).__init__(parent)
        self.setupUi(self)
        self.ok.clicked.connect(self.reject)

#########################################
# create the dialog for the about message

FORM_CLASS_ABOUT, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), '../ui/about_dialog.ui'))

class GpsInfo4ZemokostAbout(QDialog, FORM_CLASS_ABOUT):
    def __init__(self, parent=None):
        #Constructor.
        super(GpsInfo4ZemokostAbout, self).__init__(parent)
        self.setupUi(self)
        self.close.clicked.connect(self.reject)
        
        pixmap = QPixmap(os.path.join(os.path.dirname(__file__), '../images/gpsinfo_logo_pink_100px.png'))
        self.imageLabel.setPixmap(pixmap)
        self.adjustSize()
        self.setMinimumSize(self.size())
        
###########################################
# create the dialog for the warning message
FORM_CLASS_WARN, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), '../ui/warning_dialog.ui'))

class GpsInfo4ZemokostWarningDlg(QDialog, FORM_CLASS_WARN):
    def __init__(self, parent=None):
        """Constructor."""
        super(GpsInfo4ZemokostWarningDlg, self).__init__(parent)
        self.setupUi(self)
        self.closeButton.clicked.connect(self.reject)

###########################################
# create the dialog for the second warning message
FORM_CLASS_WARN_SIZE, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), '../ui/size_warning_dialog.ui'))

class GpsInfo4ZemokostSizeWarningDlg(QDialog, FORM_CLASS_WARN_SIZE):
    def __init__(self, dlg, parent=None):
        """Constructor."""
        super(GpsInfo4ZemokostSizeWarningDlg, self).__init__(parent)
        self.setupUi(self)
        self.buttonBox.accepted.connect(self.acc)
        self.buttonBox.rejected.connect(self.close)
        self.dlg = dlg

    def acc(self):
        self.close()
        self.dlg.start_process()
        QCoreApplication.processEvents() 


