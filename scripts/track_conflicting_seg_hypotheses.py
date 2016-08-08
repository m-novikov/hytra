"""
Take a set of label images that represent different segmentation hypotheses,
track them, and create a final result by cherry-picking the segments that were part of the tracking solution
"""

# pythonpath modification to make hytra available
# for import without requiring it to be installed
import os
import sys
import numpy as np
import logging
from skimage.external import tifffile
import vigra
import configargparse as argparse
sys.path.insert(0, os.path.abspath('..'))
from hytra.core.ilastikhypothesesgraph import IlastikHypothesesGraph
from hytra.core.fieldofview import FieldOfView
from hytra.pluginsystem.plugin_manager import TrackingPluginManager

try:
    import multiHypoTracking_with_cplex as mht
except ImportError:
    try:
        import multiHypoTracking_with_gurobi as mht
    except ImportError:
        raise ImportError("No version of ILP solver found")

def getLogger():
    return logging.getLogger("track_conflicting_seg_hypotheses")

def constructFov(shape, t0, t1, scale=[1, 1, 1]):
    [xshape, yshape, zshape] = shape
    [xscale, yscale, zscale] = scale

    fov = FieldOfView(t0, 0, 0, 0, t1, xscale * (xshape - 1), yscale * (yshape - 1),
                      zscale * (zshape - 1))
    return fov

def remap_label_image(label_images, mapping):
    """ 
    given a label image and a mapping, creates and 
    returns a new label image with remapped object pixel values 
    """
    remapped_label_image = np.zeros(label_images.values()[0].shape, dtype=label_images.values()[0].dtype)
    for origObject, trackId in mapping.iteritems():
        objectId, filename = origObject
        remapped_label_image[label_images[filename] == objectId] = trackId

    return remapped_label_image

def save_frame_to_tif(timestep, label_image, options):
    if options.is_groundtruth:
        filename = options.output_dir + '/man_track' + format(timestep, "0{}".format(options.filename_zero_padding)) + '.tif'
    else:
        filename = options.output_dir + '/mask' + format(timestep, "0{}".format(options.filename_zero_padding)) + '.tif'
    # label_image = np.swapaxes(label_image, 0, 1)
    if len(label_image.shape) == 2: # 2d
        vigra.impex.writeImage(label_image.astype('uint16'), filename)
    else: # 3D
        label_image = np.transpose(label_image, axes=[2, 0, 1])
        tifffile.imsave(filename, label_image.astype('uint16'))


def save_tracks(tracks, options):
    """
    Take a dictionary indexed by TrackId which contains
    a list [parent, begin, end] per track, and save it 
    in the text format of the cell tracking challenge.
    """
    if options.is_groundtruth:
        filename = options.output_dir + '/man_track.txt'
    else:
        filename = options.output_dir + '/res_track.txt'
    with open(filename, 'wt') as f:
        for key, value in tracks.iteritems():
            if key ==  None:
                continue
            # our track value contains parent, begin, end
            # but here we need begin, end, parent. so swap
            f.write("{} {} {} {}\n".format(key, value[1], value[2], value[0]))

def run_pipeline(options):
    """
    Run the complete tracking pipeline with competing segmentation hypotheses
    """
    logging.info("Create hypotheses graph...")

    import hytra.core.conflictingsegmentsprobabilitygenerator as probabilitygenerator
    from hytra.core.ilastik_project_options import IlastikProjectOptions
    ilpOptions = IlastikProjectOptions()
    ilpOptions.labelImagePath = options.label_image_paths[0]
    ilpOptions.labelImageFilename = options.label_image_files[0]

    ilpOptions.rawImagePath = options.raw_data_path
    ilpOptions.rawImageFilename = options.raw_data_file
    ilpOptions.rawImageAxes = options.raw_data_axes
    
    ilpOptions.sizeFilter = [10, 100000]
    ilpOptions.objectCountClassifierFilename = options.ilastik_tracking_project

    withDivisions = options.with_divisions
    if withDivisions:
        ilpOptions.divisionClassifierFilename = options.ilastik_tracking_project
    else:
        ilpOptions.divisionClassifierFilename = None

    probGenerator = probabilitygenerator.ConflictingSegmentsProbabilityGenerator(
        ilpOptions, 
        options.label_image_files[1:],
        options.label_image_paths[1:],
        pluginPaths=['../hytra/plugins'],
        useMultiprocessing=False)

    probGenerator.fillTraxels(usePgmlink=False)
    fieldOfView = constructFov(probGenerator.shape,
                                probGenerator.timeRange[0],
                                probGenerator.timeRange[1],
                                [probGenerator.x_scale,
                                probGenerator.y_scale,
                                probGenerator.z_scale])

    hypotheses_graph = IlastikHypothesesGraph(
        probabilityGenerator=probGenerator,
        timeRange=probGenerator.timeRange,
        maxNumObjects=1,
        numNearestNeighbors=4,
        fieldOfView=fieldOfView,
        withDivisions=withDivisions,
        divisionThreshold=0.1
    )

    # if options.with_tracklets:
    #     hypotheses_graph = hypotheses_graph.generateTrackletGraph()

    hypotheses_graph.insertEnergies()
    trackingGraph = hypotheses_graph.toTrackingGraph()
    
    if options.do_convexify:
        logging.info("Convexifying graph energies...")
        trackingGraph.convexifyCosts()

    # track
    logging.info("Run tracking...")
    result = mht.track(trackingGraph.model, {"weights" : [10, 10, 10, 500, 500]})

    # insert the solution into the hypotheses graph and from that deduce the lineages
    hypotheses_graph.insertSolution(result)
    hypotheses_graph.computeLineage()

    mappings = {} # dictionary over timeframes, containing another dict objectId -> trackId per frame
    tracks = {} # stores a list of timeframes per track, so that we can find from<->to per track
    trackParents = {} # store the parent trackID of a track if known

    for n in hypotheses_graph.nodeIterator():
        frameMapping = mappings.setdefault(n[0], {})
        if 'trackId' not in hypotheses_graph._graph.node[n]:
            raise ValueError("You need to compute the Lineage of every node before accessing the trackId!")
        trackId = hypotheses_graph._graph.node[n]['trackId']
        traxel = hypotheses_graph._graph.node[n]['traxel']
        if trackId is not None:
            frameMapping[(traxel.idInSegmentation, traxel.segmentationFilename)] = trackId
        if trackId in tracks:
            tracks[trackId].append(n[0])
        else:
            tracks[trackId] = [n[0]]
        if 'parent' in hypotheses_graph._graph.node[n]:
            assert(trackId not in trackParents)
            trackParents[trackId] = hypotheses_graph._graph.node[hypotheses_graph._graph.node[n]['parent']]['trackId']

    # write res_track.txt
    getLogger().debug("Writing track text file")
    trackDict = {}
    for trackId, timestepList in tracks.iteritems():
        timestepList.sort()
        try:
            parent = trackParents[trackId]
        except KeyError:
            parent = 0
        trackDict[trackId] = [parent, min(timestepList), max(timestepList)]
    save_tracks(trackDict, options) 

    # export results
    getLogger().debug("Saving relabeled images")
    pluginManager = TrackingPluginManager(verbose=options.verbose, pluginPaths=options.pluginPaths)
    pluginManager.setImageProvider('LocalImageLoader')
    imageProvider = pluginManager.getImageProvider()
    timeRange = imageProvider.getTimeRange(options.label_image_files[0], options.label_image_paths[0])

    for timeframe in range(timeRange[0], timeRange[1]):
        label_images = {}
        for f, p in zip(options.label_image_files, options.label_image_paths):
            label_images[f] = imageProvider.getLabelImageForFrame(f, p, timeframe)
        remapped_label_image = remap_label_image(label_images, mappings[timeframe])
        save_frame_to_tif(timeframe, remapped_label_image, options)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Multi-Segmentation-Hypotheses Tracking Pipeline',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-c', '--config', is_config_file=True, help='config file path', dest='config_file', required=False)

    parser.add_argument("--do-convexify", dest='do_convexify', action='store_true', default=False)
    parser.add_argument("--ilastik-tracking-project", dest='ilastik_tracking_project', required=True,
                        type=str, help='ilastik tracking project file that contains the chosen weights')
    parser.add_argument('--plugin-paths', dest='pluginPaths', type=str, nargs='+',
                        default=[os.path.abspath('../hytra/plugins')],
                        help='A list of paths to search for plugins for the tracking pipeline.')
    parser.add_argument("--verbose", dest='verbose', action='store_true', default=False)
    parser.add_argument('--with-divisions', dest='with_divisions', action='store_true')

    # Raw Data:
    parser.add_argument('--raw-data-file', type=str, dest='raw_data_file', default=None,
                      help='filename to the raw h5 file')
    parser.add_argument('--raw-data-path', type=str, dest='raw_data_path', default='exported_data',
                      help='Path inside the raw h5 file to the data')
    parser.add_argument("--raw-data-axes", dest='raw_data_axes', type=str, default='txyzc',
                        help="axes ordering of the produced raw image, e.g. xyztc.")

    # Label images:
    parser.add_argument('--label-image-file', type=str, dest='label_image_files', action='append',
                      help='Label image filenames of the different segmentation hypotheses')
    parser.add_argument('--label-image-path', dest='label_image_paths', type=str, action='append',
                        help='''internal hdf5 path to label image. If only exactly one argument is given, it will be used for all label images,
                        otherwise there need to be as many label image paths as filenames.
                        Defaults to "/TrackingFeatureExtraction/LabelImage/0000/[[%d, 0, 0, 0, 0], [%d, %d, %d, %d, 1]]" for all images if not specified''')

    # Output
    parser.add_argument('--ctc-output-dir', type=str, dest='output_dir', default=None, required=True,
                      help='foldername in which all the output is stored')
    parser.add_argument('--is-gt', dest='is_groundtruth', action='store_true')
    parser.add_argument('--ctc-filename-zero-pad-length', type=int, dest='filename_zero_padding', default='3')

    # parse command line
    options, unknown = parser.parse_known_args()

    if options.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    logging.debug("Ignoring unknown parameters: {}".format(unknown))

    # assert(len(options.label_image_files) > 1)
    if options.label_image_paths is None or len(options.label_image_paths) == 0:
        options.label_image_paths = ['/TrackingFeatureExtraction/LabelImage/0000/[[%d, 0, 0, 0, 0], [%d, %d, %d, %d, 1]]']
    if len(options.label_image_paths) < len(options.label_image_files) and len(options.label_image_paths) == 1:
        options.label_image_paths = options.label_image_paths * len(options.label_image_files)   
    assert(len(options.label_image_paths) == len(options.label_image_files) )

    # make sure output directory exists
    if not os.path.exists(options.output_dir):
        os.makedirs(options.output_dir)

    run_pipeline(options)
