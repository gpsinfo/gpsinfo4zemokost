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
from PyQt5.QtWidgets import QTableWidgetItem
from PyQt5.QtCore import QCoreApplication # import QCoreApplication.processEvents
from osgeo import gdal, ogr
from qgis.core import QgsProject, QgsMapLayer, QgsWkbTypes
from osgeo.osr import SpatialReference
# standard python modules
from zipfile import ZipFile
from io import BytesIO
from numpy import array, ndarray

# custom modules
from .gpsinfo4zemokost_dialog import GpsInfo4ZemokostWarningDlg



# This function (process) is the outer frame of the result creation.
# The main task of downloading and processing the tiles is done by 
# the function clipped_raster, defined below.
def process(dlg):
    # :param dlg --- the plugins main dialog defined in gps_info_4_zemokost.py

    # tile data 
    TD = {'NCOLS':150, 'NROWS':150, 'EPSG':'EPSG:31287',
          'XLL':106549.267203768890, 'YLL':273692.512073625810, 
          'CELLSIZE':10.000000000000, 'NODATA':-99999}

    # decide whether to calculate mean only for ...
    # ... selected feature (False) or entire layer (True)
    only_sel = dlg.onlySelFeat.isChecked()
 
    # get a feature iterator                        
    if dlg.onlySelFeat.isChecked():
        feats = list(dlg.selected_layer.getSelectedFeatures())
    else:
        feats = list(dlg.selected_layer.getFeatures())

    # compute the max number of tiles, needed to set up the progress bar.
    nr_of_tiles_dl = 0
    
    # tile numbers for the merged dataset. Initialize with some values
    tile_nr_left_m = 99999
    tile_nr_right_m = -99999
    tile_nr_bottom_m = 99999
    tile_nr_top_m = -99999


    for f in feats:
        bb = f.geometry().boundingBox()
        xmin, xmax, ymin, ymax = bb.xMinimum(), bb.xMaximum(), bb.yMinimum(), bb.yMaximum()

        tile_nr_left   = int((xmin - TD['XLL']) // (TD['CELLSIZE'] * TD['NCOLS']))
        tile_nr_right  = int((xmax - TD['XLL']) // (TD['CELLSIZE'] * TD['NCOLS']))
        nr_of_tiles_x  = tile_nr_right - tile_nr_left+1
        tile_nr_bottom = int((ymin - TD['YLL']) // (TD['CELLSIZE'] * TD['NROWS']))
        tile_nr_top    = int((ymax  - TD['YLL']) // (TD['CELLSIZE'] * TD['NROWS']))
        nr_of_tiles_y  = tile_nr_top - tile_nr_bottom+1
 
        nr_of_tiles_dl += nr_of_tiles_x * nr_of_tiles_y
        tile_nr_left_m = min(tile_nr_left_m, tile_nr_left)
        tile_nr_right_m = max(tile_nr_right_m, tile_nr_right)
        tile_nr_bottom_m = min(tile_nr_bottom_m, tile_nr_bottom)
        tile_nr_top_m = max(tile_nr_top_m, tile_nr_top)

    nr_of_tiles_x_m = tile_nr_right_m - tile_nr_left_m + 1
    nr_of_tiles_y_m = tile_nr_top_m - tile_nr_bottom_m + 1

    # in case we want to save the raster data, set up a raster driver for the whole region
    if dlg.rasterFilePath.text() != '' and dlg.rasterCheck.isChecked():
        driver_m = gdal.GetDriverByName( 'MEM' )
        ds_m = driver_m.Create('', TD['NCOLS'] * nr_of_tiles_x_m, TD['NROWS'] * nr_of_tiles_y_m, 1, gdal.GDT_Float32)

        # fetch geotransform for upper left tile
        www_layer_name = 'AT_OGD_DHM_LAMB_10M_SLOPE'
        www_folder = 'http://gpsinfo.org/service/' + www_layer_name + '_COMPRESSED/'
        url = '/vsizip//vsicurl/' + www_folder + str(tile_nr_left_m)+'/'+str(tile_nr_top_m)
        url += '.asc.zip/' + www_layer_name + '_TILED/'
        url += str(tile_nr_left_m)+'/'+str(tile_nr_top_m)+'.asc'

        ds_tl = gdal.Open(url)             # open .asc file

        # set geotransform of merged raster to that of upper left tile
        ds_m.SetGeoTransform(ds_tl.GetGeoTransform())
        #dlg.label.setText(str(geo_trafo_tl))

        # initialize an array of the necessary dimension
        merged_array = ndarray((TD['NROWS'] * nr_of_tiles_y_m, TD['NCOLS'] * nr_of_tiles_x_m), dtype = float)
        merged_array[:,:] = TD['NODATA']
    else: 
        merged_array = 0


    # set up the progress bar
    dlg.progressBar.setMinimum(0)
    dlg.progressBar.setMaximum(nr_of_tiles_dl)
    dlg.setProgressValue(0)

    # The features in feats may contain no data points. Define a counter for those features which have
    # no no data points, that is, only valid points.
    j = 0

    # collect the clipped datasets in case we want to save them
    clipped_datasets = []

    # Define a warning message for features containing no data points
    warning = ''
    # too small features
    too_sm_feats = 0
    for i in range(len(feats)):

        vals, nodata_pt = clipped_raster(dlg, feats[i], TD, merged_array, tile_nr_left_m, tile_nr_bottom_m, nr_of_tiles_x_m, nr_of_tiles_y_m)
            
        if len(nodata_pt) == 0 and len(vals) != 0: 

            # add a row to the result table    
            dlg.resultTable.setRowCount(dlg.resultTable.rowCount() + 1)
            dlg.resultTable.setEnabled(True)

            # compute the centroid as a QgsPointXY object
            c = feats[i].geometry().centroid().asPoint()
            # fill the result table
            dlg.resultTable.setItem(j, 0, QTableWidgetItem(str(feats[i].attributes()[0])))
            dlg.resultTable.setItem(j, 1, QTableWidgetItem('({:.1f}, {:.1f})'.format(c.x(), c.y() )))
            # area in square km:
            dlg.resultTable.setItem(j, 2, QTableWidgetItem('{:.5f}'.format(feats[i].geometry().area() / 1000000 )))
            dlg.resultTable.setItem(j, 3, QTableWidgetItem('{:.5f}'.format(sum(vals) / len(vals) )))

            dlg.resultTable.resizeColumnsToContents()
            j += 1
            QCoreApplication.processEvents()
        elif len(nodata_pt) != 0:
            warning += ('In einem Feature mit {} = {} wurden keine Daten abgefragt, weil an den'
                        ' Koordinaten ({:.0f}, {:.0f}) ein Punkt ohne Daten gefunden wurde.\n\n'
                        '\n\n').format(feats[i].fields()[0].name(), str(feats[i].attributes()[0]), 
                                       nodata_pt[0], nodata_pt[1]) 

        elif len(nodata_pt) == 0 and len(vals) == 0:   # in this case, the feature is too small.
            too_sm_feats += 1

    # write an error text if there are too small features
    if too_sm_feats == 1:
        warning += ('Ein Feature ist kleiner als die Auflösung des '
                    'zugrundeliegenden Rasterdatensatzes und wird nicht in '
                    'der Tabelle dargestellt.\n\n')

    if too_sm_feats >= 2:
        warning += ('{} Features sind kleiner als die Auflösung des '
                    'zugrundeliegenden Rasterdatensatzes und werden nicht in '
                    'der Tabelle dargestellt.\n\n').format(too_sm_feats)

    # remove the last two newlines
    warning = warning.rstrip('\n\n')

    
    if dlg.rasterFilePath.text() != '' and dlg.rasterCheck.isChecked():
        dlg.progressBar.setFormat('Speichere Rasterdaten')
        QCoreApplication.processEvents()
        ds_m.GetRasterBand(1).WriteArray(merged_array)
        gdal.Translate(dlg.rasterFilePath.text(), ds_m, format = 'AAIGrid', noData = TD['NODATA']) 


  


    dlg.progressBar.setFormat('Berechnung beendet.')
    # enable save button
    dlg.saveButton.setEnabled(True)

        
    return warning


# for given "feature", the following function computes which tiles are necessary,
# downloads them from the internet, clips the tiles to the extent of the feature
# and collects the data values in a list, called "vals".
def clipped_raster(dlg, feature, TD, merged_array, tile_nr_left_m, tile_nr_bottom_m, nr_of_tiles_x_m, nr_of_tiles_y_m):
    # TD --- basically contains the data stored in the header of 0_0.asc 
    # file_path --- if empty string or false, the clipped tiles are not saved.
    #               if it is a filename, they are saved. This is for checking the result!            

    www_layer_name = 'AT_OGD_DHM_LAMB_10M_SLOPE'
    www_folder = 'http://gpsinfo.org/service/' + www_layer_name + '_COMPRESSED/'

    ################################################################
    # STEP 1 -- PREPARE THE GDAL-FEATURE-LAYER
    ################################################################ 
 
    # remove the Z-dimension and M-dimension, if present
    abs_geom = feature.geometry().constGet()
    abs_geom.dropZValue()
    abs_geom.dropMValue()

    # represent feature as WellKnownText-format so we can import it in ogr
    feat_wkt = abs_geom.asWkt()

    # create a memory vector driver and datasource for the feature
    driver = ogr.GetDriverByName('Memory')
    ds = driver.CreateDataSource('out')
    # set srs
    spa = SpatialReference()
    spa.ImportFromEPSG(31287)
    # create a layer
    layer = ds.CreateLayer('selected_feature', srs = spa)
    # create a gdal feature from the wkt-repr. of the qgis feature
    geom = ogr.CreateGeometryFromWkt(feat_wkt)
    gdal_feat = ogr.Feature(ogr.FeatureDefn())
    gdal_feat.SetGeometryDirectly(geom)
    # add it to the layer
    layer.SetFeature(gdal_feat)
    # and get the bounding box
    x_min, x_max, y_min, y_max = layer.GetExtent()
            

    ################################################################
    # STEP 2 -- determine, download and process the necessary tiles
    ################################################################ 
    # compute which tiles are required, "TD" stands for "tile data"
    tile_nr_left   = int((x_min - TD['XLL']) // (TD['CELLSIZE'] * TD['NCOLS']))
    tile_nr_right  = int((x_max - TD['XLL']) // (TD['CELLSIZE'] * TD['NCOLS']))
    nr_of_tiles_x  = tile_nr_right - tile_nr_left+1
    tile_nr_bottom = int((y_min - TD['YLL']) // (TD['CELLSIZE'] * TD['NROWS']))
    tile_nr_top    = int((y_max  - TD['YLL']) // (TD['CELLSIZE'] * TD['NROWS']))
    nr_of_tiles_y  = tile_nr_top - tile_nr_bottom+1

    # initialize the return values
    vals = list()
    nodata_pt = []
    # data_counter = 0

    # iterate through all the tiles needed to cover the bounding box of the feature
    for ix in range(nr_of_tiles_x):
        for iy in range(nr_of_tiles_y):
            ##########
            # STEP 2.1
            ##########
            # check if the tile (ix,iy) really intersects the feature:
            # create a rectangle of the size of the tile
            # to be on safe side, make rectangle slightly smaller than tile
            x_left = TD['XLL'] + ((ix + tile_nr_left) * TD['NCOLS'] +1) * TD['CELLSIZE']
            x_right = TD['XLL'] + ((ix + tile_nr_left) + 1) * TD['NCOLS'] * TD['CELLSIZE']
            y_bottom = TD['YLL'] + ((iy + tile_nr_bottom) * TD['NROWS'] +1) * TD['CELLSIZE']
            y_top = TD['YLL'] + ((iy + tile_nr_bottom) +1 ) * TD['NROWS'] * TD['CELLSIZE']

            rect = ogr.Geometry(ogr.wkbLinearRing)
            rect.AddPoint(x_left, y_bottom)
            rect.AddPoint(x_right, y_bottom)
            rect.AddPoint(x_right, y_top)
            rect.AddPoint(x_left, y_top)
            rect.AddPoint(x_left, y_bottom)

            poly = ogr.Geometry(ogr.wkbPolygon)
            poly.AddGeometry(rect)

            # only download and process the tile if it intersects the feature (geom)
            # and if no no-data points have been found yet
            if poly.Intersects(geom) and len(nodata_pt) == 0:
                ##########
                # STEP 2.2, download, unzip and open the tile with gdal
                ##########
                url = '/vsizip//vsicurl/' + www_folder + str(tile_nr_left+ix)+'/'+str(tile_nr_bottom+iy)+\
                      '.asc.zip/' + www_layer_name + '_TILED/' + \
                      str(tile_nr_left+ix)+'/'+str(tile_nr_bottom+iy)+'.asc'
                ds_www = gdal.Open(url)             # open .asc file
                # save its GeoTransform
                geo_trafo = ds_www.GetGeoTransform()
    

                ##########
                # STEP 2.3, rasterize the polygon feature. "_m" means "mask".
                ##########
                driver_m = gdal.GetDriverByName( 'MEM' )
                ds_m = driver_m.Create('', TD['NCOLS'], TD['NROWS'], 1, gdal.GDT_Int32)
                ds_m.SetGeoTransform(geo_trafo)
                # burn the mask values: 1 inside polygon feature, 0 outside
                gdal.RasterizeLayer(ds_m, [1], layer, burn_values = [1])
                #gdal.Rasterize(ds_m, ds)#, burnValues = [1], allTouched = True)
            

                ##########
                # STEP 2.3, multiply the rasterized polygon with the downloaded tile, thereby creating clipped_array
                ##########
                array_m = ds_m.ReadAsArray()
                array_www = ds_www.ReadAsArray()
                shp = array_www.shape

                # iterate over the elements of the array
                for i in range(shp[0]):
                    for j in range(shp[1]):
                        if array_m[i,j] == 1:       # if "(i,j)" is inside polygon:
                            if array_www[i,j] == TD['NODATA']:      # if point is nodata point
                                nodata_pt = gdal.ApplyGeoTransform(geo_trafo, j + 0.5, i + 0.5)
                            else:
                                vals.append(array_www[i,j])

                                if dlg.rasterFilePath.text() != '' and dlg.rasterCheck.isChecked():  # if raster should be saved
                                    # fill the merged array
                                    I = (nr_of_tiles_y_m - (tile_nr_bottom - tile_nr_bottom_m + iy + 1))* TD['NROWS'] + i
                                    J = (tile_nr_left - tile_nr_left_m + ix) * TD['NCOLS'] + j
                                  
                                    merged_array[I, J] = array_www[i, j]


            else:
                # this is the case that either we have already found a no data point inside the polygon
                # or the tile doesn't intersect the polygon
                pass  
            
            dlg.setProgressValue(dlg.progressBar.value()+1)
            QCoreApplication.processEvents()
            
    return vals, nodata_pt

def load_layers(iface):
    # Load a dictionary of layerId:layer pairs
    layer_dic = QgsProject.instance().layerStore().mapLayers()
    
    # Filter the vector layers (LayerType(0))
    vec_dic = dict()
    for l in layer_dic:
        if layer_dic[l].type() == QgsMapLayer.LayerType(0):
            vec_dic[l] = layer_dic[l]

    # Further filter those polygon layers (geometryType(2)) which have 
    #          at least 1 feature and add them to the drop down menu. 
    poly_geom = QgsWkbTypes.GeometryType(2)
    poly_dic = dict()
    poly_ind = []        # Indices are saved here
    for l in vec_dic:
        if vec_dic[l].geometryType() == poly_geom and vec_dic[l].featureCount() and vec_dic[l].crs().authid() == 'EPSG:31287':
            poly_dic[l] = vec_dic[l]
            poly_ind.append(l)

    return poly_dic, poly_ind


