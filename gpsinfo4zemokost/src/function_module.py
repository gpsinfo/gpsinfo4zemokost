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
import requests

# custom modules
from .gpsinfo4zemokost_dialog import GpsInfo4ZemokostWarningDlg

# --------------------------------------------------------------------------------------
# -------------------- some global values ----------------------------------------------
# --------------------------------------------------------------------------------------
# tile data 
TD = {'NCOLS':150, 'NROWS':150, 'EPSG':'EPSG:31287',
      'XLL':106549.267203768890, 'YLL':273692.512073625810, 
      'CELLSIZE':10.000000000000, 'NODATA':-99999}

www_layer_name = 'AT_OGD_DHM_LAMB_10M_SLOPE'
www_folder = 'https://austrian-geodata-services.org/gpsinfo/' + www_layer_name + '_COMPRESSED/'

# This function (process) is the outer frame of the result creation.
# The main task of downloading and processing the tiles is done by 
# the function clipped_raster, defined below.
def process(dlg, post_warn_dlg):
    # :param dlg --- the plugins main dialog defined in gps_info_4_zemokost.py



    # decide whether to calculate mean only for ...
    # ... selected feature (False) or entire layer (True)
    only_sel = dlg.onlySelFeat.isChecked()
 
    # get a feature iterator                        
    if dlg.onlySelFeat.isChecked():
        feats = list(dlg.selected_layer.getSelectedFeatures())
    else:
        feats = list(dlg.selected_layer.getFeatures())

    
    # Define a warning message for features containing no data points and those outside the data region
    warning = ''

    # Compute the number of tiles that get processed (not necessarily all of them are downloaded).
    # This needed to set up the progress bar.
    nr_of_tiles_dl = 0

    # tile bounding box for the merged dataset. Initialize with some values
    TN_l_tot, TN_r_tot, TN_b_tot, TN_t_tot= 99999, -99999, 99999, -99999

    valid_feats = []

    for f in feats:
        # compute the tiles required for feature f
        bb = f.geometry().boundingBox()
        xmin, xmax, ymin, ymax = bb.xMinimum(), bb.xMaximum(), bb.yMinimum(), bb.yMaximum()
        TN_l, TN_r, TN_b, TN_t = compute_tile_bb(xmin, xmax, ymin, ymax)


        # make sure the the feature is covered by the data region
        if TN_l < 0 or TN_b < 0 or TN_r > 392 or TN_t > 202:
            post_warn_dlg.add_warning(  ('In einem Feature mit {} = {} wurden keine Daten abgefragt, weil es'
                        ' außerhalb des Datensatzes liegt.').format(f.fields()[0].name(), str(f.attributes()[0])) )
        else: 
            valid_feats.append(f)
            nr_of_tiles_dl += (TN_r - TN_l+1) * (TN_t - TN_b+1)

            # update 
            TN_l_tot = min(TN_l_tot, TN_l)
            TN_r_tot = max(TN_r_tot, TN_r)
            TN_b_tot = min(TN_b_tot, TN_b)
            TN_t_tot = max(TN_t_tot, TN_t)



    nr_of_tiles_x_tot = TN_r_tot - TN_l_tot + 1
    nr_of_tiles_y_tot = TN_t_tot - TN_b_tot + 1

    # check whether gdal.Open works. Consequently, set downloader to gdal_downloader (gdal.Open) or alt_downloader
    downloader = gdal_downloader
    # try downloading the tile (1, 1)
    if downloader(1, 1) == None:
        downloader = alt_downloader

    # in case we want to save the raster data, set up a raster driver for the whole region
    if dlg.rasterFilePath.text() != '' and dlg.rasterCheck.isChecked():
        dr_tot = gdal.GetDriverByName( 'MEM' )
        ds_tot = dr_tot.Create('', TD['NCOLS'] * nr_of_tiles_x_tot, TD['NROWS'] * nr_of_tiles_y_tot, 1, gdal.GDT_Float32)

        # fetch geotransform for upper left tile
        ds_ul = downloader(TN_l_tot, TN_t_tot)         # open .asc file

        # set geotransform of merged raster to that of upper left tile
        ds_tot.SetGeoTransform(ds_ul.GetGeoTransform())

        # initialize an array of the necessary dimension
        merged_array = ndarray((TD['NROWS'] * nr_of_tiles_y_tot, TD['NCOLS'] * nr_of_tiles_x_tot), dtype = float)
        merged_array[:,:] = TD['NODATA']
    else: 
        merged_array = 0


    # set up the progress bar
    dlg.progressBar.setMinimum(0)
    dlg.progressBar.setMaximum(nr_of_tiles_dl)
    dlg.setProgressValue(0)

    # The features in valid_feats may still contain no data points. Define a counter for those features which have
    # no no data points, that is, only valid points.
    j = 0

    # collect the clipped datasets in case we want to save them
    clipped_datasets = []

    # number of too small features
    nr_too_sm_feats = 0
    for i in range(len(valid_feats)):

        vals, nodata_pt = clipped_raster(dlg, valid_feats[i], merged_array, downloader, TN_l_tot, TN_b_tot, nr_of_tiles_x_tot, nr_of_tiles_y_tot)
            
        if len(nodata_pt) == 0 and len(vals) != 0: 

            # add a row to the result table    
            dlg.resultTable.setRowCount(dlg.resultTable.rowCount() + 1)
            dlg.resultTable.setEnabled(True)

            # compute the centroid as a QgsPointXY object
            c = valid_feats[i].geometry().centroid().asPoint()
            # fill the result table
            dlg.resultTable.setItem(j, 0, QTableWidgetItem(str(valid_feats[i].attributes()[0])))
            dlg.resultTable.setItem(j, 1, QTableWidgetItem('({:.1f}, {:.1f})'.format(c.x(), c.y() )))
            # area in square km:
            dlg.resultTable.setItem(j, 2, QTableWidgetItem('{:.5f}'.format(valid_feats[i].geometry().area() / 1000000 )))
            dlg.resultTable.setItem(j, 3, QTableWidgetItem('{:.5f}'.format(sum(vals) / len(vals) )))

            dlg.resultTable.resizeColumnsToContents()
            j += 1
            QCoreApplication.processEvents()
        elif len(nodata_pt) != 0:
            post_warn_dlg.add_warning( ('In einem Feature mit {} = {} wurden keine Daten abgefragt, weil an den'
                                        ' Koordinaten ({:.0f}, {:.0f}) ein Punkt ohne Daten gefunden '
                                        'wurde.').format(valid_feats[i].fields()[0].name(),
                                                         str(valid_feats[i].attributes()[0]), 
                                                         nodata_pt[0], nodata_pt[1]) )

        elif len(nodata_pt) == 0 and len(vals) == 0:   # in this case, the feature is too small.
            nr_too_sm_feats += 1

    # write an error text if there are too small features
    if nr_too_sm_feats == 1:
        post_warn_dlg.add_warning( ('Ein Feature ist kleiner als die Auflösung des '
                    'zugrundeliegenden Rasterdatensatzes und wird nicht in '
                    'der Tabelle dargestellt.')  )

    if nr_too_sm_feats >= 2:
        post_warn_dlg.add_warning( ('{} Features sind kleiner als die Auflösung des '
                    'zugrundeliegenden Rasterdatensatzes und werden nicht in '
                    'der Tabelle dargestellt.').format(nr_too_sm_feats) )

    
    if dlg.rasterFilePath.text() != '' and dlg.rasterCheck.isChecked():
        dlg.progressBar.setFormat('Speichere Rasterdaten')
        QCoreApplication.processEvents()
        ds_tot.GetRasterBand(1).WriteArray(merged_array)

        try:
            gdal.Translate(dlg.rasterFilePath.text(), ds_tot, format = 'AAIGrid', noData = TD['NODATA']) 
        except:
            post_warn_dlg.add_warning('There was an error writing the raster data to file.')

    dlg.progressBar.setFormat('Berechnung beendet.')
    # enable save button
    dlg.saveButton.setEnabled(True)




# for given "feature", the following function computes which tiles are necessary,
# downloads them from the internet, clips the tiles to the extent of the feature
# and collects the data values in a list, called "vals".
def clipped_raster(dlg, feature, merged_array, downloader, TN_l_tot, TN_b_tot, nr_of_tiles_x_tot, nr_of_tiles_y_tot):

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
            

    ################################################################
    # STEP 2 -- determine, download and process the necessary tiles
    ################################################################ 

    # get the coordinate bounding box
    x_totin, x_totax, y_totin, y_totax = layer.GetExtent()
    # and from it the tile bounding box
    TN_l, TN_r, TN_b, TN_t = compute_tile_bb(x_totin, x_totax, y_totin, y_totax)

    # initialize the return values
    vals = list()
    nodata_pt = []

    # iterate through all the tiles needed to cover the bounding box of the feature
    for ix in range(TN_r - TN_l+1):
        for iy in range(TN_t - TN_b+1):
            ##########
            # STEP 2.1
            ##########
            # check if the tile (ix,iy) really intersects the feature:
            # create a rectangle of the size of the tile
            # to be on safe side, make rectangle slightly smaller than tile
            x_left = TD['XLL'] + ((ix + TN_l) * TD['NCOLS'] +1) * TD['CELLSIZE']
            x_right = TD['XLL'] + ((ix + TN_l) + 1) * TD['NCOLS'] * TD['CELLSIZE']
            y_bottom = TD['YLL'] + ((iy + TN_b) * TD['NROWS'] +1) * TD['CELLSIZE']
            y_top = TD['YLL'] + ((iy + TN_b) +1 ) * TD['NROWS'] * TD['CELLSIZE']

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

                ds_www = downloader(TN_l+ix, TN_b+iy)             # open .asc file
                # save its GeoTransform
                geo_trafo = ds_www.GetGeoTransform()
    

                ##########
                # STEP 2.3, rasterize the polygon feature. "_m" means "mask".
                ##########
                dr_m = gdal.GetDriverByName( 'MEM' )
                ds_m = dr_m.Create('', TD['NCOLS'], TD['NROWS'], 1, gdal.GDT_Int16)
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


                                # if raster should be saved
                                if dlg.rasterFilePath.text() != '' and dlg.rasterCheck.isChecked():  

                                    # fill the merged array
                                    I = (nr_of_tiles_y_tot - (TN_b - TN_b_tot + iy + 1))* TD['NROWS'] + i
                                    J = (TN_l - TN_l_tot + ix) * TD['NCOLS'] + j
                                  
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

# this downloader is default
def gdal_downloader(tile_nr_x, tile_nr_y):

    url = '/vsizip//vsicurl/' + www_folder + str(tile_nr_x)+'/'+str(tile_nr_y)+\
                      '.asc.zip/' + www_layer_name + '_TILED/' + \
                      str(tile_nr_x)+'/'+str(tile_nr_y)+'.asc'

    return gdal.Open(url)

# this alternative downloader is used if gdal.Open does not work
def alt_downloader(tile_nr_x, tile_nr_y):

    # construct url
    url = www_folder + str(tile_nr_x) + '/' + str(tile_nr_y) + '.asc.zip'


    try:
        # create a momemory driver and dataset on it
        driver = gdal.GetDriverByName( 'MEM' )
        ds = driver.Create('', TD['NCOLS'], TD['NROWS'], 1, gdal.GDT_Float32)

        # access the zip file
        zf = ZipFile(BytesIO(requests.get(url).content))

        # read the rasterfile in the format of an array
        lines = zf.open(zf.infolist()[0]).readlines()

        # NOTE:
        # in the following lines we use some properties that the .asc files on our server have:
        # - carriage returns are used to separate header items and rows
        # - the header is 6 lines, that is, there is a NO DATA value in line 6
        # - the data starts in line 7 (index 6)
        # these are not required by the standard, c.f. 
        # http://help.arcgis.com/en/arcgisdesktop/10.0/help/index.html#/ESRI_ASCII_raster_format/009t0000000z000000/
        # in particular, NO DATA is optional and carriage returns may be replaced by spaces

        # read the geo transform
    
        #as from http://geoexamples.blogspot.com/2012/01/creating-files-in-ogr-and-gdal-with.html:

        #geotransform = (left x-coordinate, x-cellsize, rotation ?,upper y-coordinate,rotation,y-cellsize)

        #Xgeo = geotransform[0] + Xpixel*geotransform[1] + Yline*geotransform[2]
        #Ygeo = geotransform[3] + Xpixel*geotransform[4] + Yline*geotransform[5]

        #for some reason, y-cellsize must be negative here
    
        geo_trafo = (float(lines[2].split()[1]), TD['CELLSIZE'], 0,
                float(lines[3].split()[1]) + TD['CELLSIZE'] * TD['NROWS'],0 , -TD['CELLSIZE'])

        ds.SetGeoTransform(geo_trafo)

        # read and write the data to the dataset
        arr = list(map(lambda x : list(map(float,x.split())),lines[6:]))
        zf.close()
        band = ds.GetRasterBand(1)
        band.WriteArray(array(arr))

        # set the spatial reference system (probably not necessary)
        proj = SpatialReference()
        proj.SetWellKnownGeogCS("EPSG:31287")
        ds.SetProjection(proj.ExportToWkt())

        return ds

    except:  
        return None

def compute_tile_bb(xmin, xmax, ymin, ymax):
    # compute the tile numbers corresponding to xmin, xmax, ymin, ymay
    TN_l  = int((xmin - TD['XLL']) // (TD['CELLSIZE'] * TD['NCOLS']))
    TN_r  = int((xmax - TD['XLL']) // (TD['CELLSIZE'] * TD['NCOLS']))
    TN_b = int((ymin - TD['YLL']) // (TD['CELLSIZE'] * TD['NROWS']))
    TN_t    = int((ymax  - TD['YLL']) // (TD['CELLSIZE'] * TD['NROWS']))

    return TN_l, TN_r, TN_b, TN_t  


