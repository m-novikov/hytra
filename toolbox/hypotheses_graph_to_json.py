#!/usr/bin/env python
import sys
import os
import os.path as path
import glob
import optparse
import time
import numpy as np
import h5py
import json
from progressbar import ProgressBar
import hypothesesgraph
import logging



def getConfigAndCommandLineArguments():
    usage = """%prog [options] FILES
    Track cells.

    Before processing, input files are copied to OUT_DIR. Groups, that will not be modified are not
    copied but linked to the original files to improve execution speed and storage requirements.
    """

    parser = optparse.OptionParser(usage=usage)
    parser.add_option('--config-file', type='string', dest='config', default=None,
                      help='path to config file')
    parser.add_option('--method', type='str', default='conservation',
                      help='conservation or conservation-dynprog [default: %default]')
    parser.add_option('-o', '--output-dir', type='str', dest='out_dir', default='tracked', help='[default: %default]')
    parser.add_option('--x-scale', type='float', dest='x_scale', default=1., help='[default: %default]')
    parser.add_option('--y-scale', type='float', dest='y_scale', default=1., help='[default: %default]')
    parser.add_option('--z-scale', type='float', dest='z_scale', default=1., help='[default: %default]')
    parser.add_option('--comment', type='str', dest='comment', default='none',
                      help='some comment to log [default: %default]')
    parser.add_option('--random-forest', type='string', dest='rf_fn', default=None,
                      help='use cellness prediction instead of indicator function for (mis-)detection energy')
    parser.add_option('-f', '--forbidden_cost', type='float', dest='forbidden_cost', default=0,
                      help='forbidden cost [default: %default]')
    parser.add_option('--min-ts', type='int', dest='mints', default=0, help='[default: %default]')
    parser.add_option('--max-ts', type='int', dest='maxts', default=-1, help='[default: %default]')
    parser.add_option('--min-size', type='int', dest='minsize', default=0,
                      help='minimal size of objects to be tracked [default: %default]')
    parser.add_option('--max-size', type='int', dest='maxsize', default=100000,
                      help='maximal size of objects to be tracked [default: %default]')
    parser.add_option('--dump-traxelstore', type='string', dest='dump_traxelstore', default=None,
                      help='dump traxelstore to file [default: %default]')
    parser.add_option('--load-traxelstore', type='string', dest='load_traxelstore', default=None,
                      help='load traxelstore from file [default: %default]')
    parser.add_option('--raw-data-file', type='string', dest='raw_filename', default=None,
                      help='filename to the raw h5 file')
    parser.add_option('--raw-data-path', type='string', dest='raw_path', default='volume/data',
                      help='Path inside the raw h5 file to the data')
    parser.add_option('--dump-hypotheses-graph', type='string', dest='hypotheses_graph_filename', default=None,
                      help='save hypotheses graph so it can be loaded later')
    parser.add_option('--label-image-file', type='string', dest='label_image_file', default=None,
                      help='if a label image separate to the one in the ILP should be used, set it here')

    parser.add_option('--json-output', type='string', dest='json_filename', default=None,
                      help='filename where to save the generated JSON file to')

    consopts = optparse.OptionGroup(parser, "conservation tracking")
    consopts.add_option('--max-number-objects', dest='max_num_objects', type='float', default=2,
                        help='Give maximum number of objects one connected component may consist of [default: %default]')
    consopts.add_option('--max-neighbor-distance', dest='mnd', type='float', default=30, help='[default: %default]')
    consopts.add_option('--max-nearest-neighbors', dest='max_nearest_neighbors', type='int', default=1,
                        help='[default: %default]')
    consopts.add_option('--division-threshold', dest='division_threshold', type='float', default=0.1,
                        help='[default: %default]')
    # detection_rf_filename in general parser options
    consopts.add_option('--size-dependent-detection-prob', dest='size_dependent_detection_prob', action='store_true')
    # forbidden_cost in general parser options
    # ep_gap in general parser options
    consopts.add_option('--average-obj-size', dest='avg_obj_size', type='float', default=0, help='[default: %default]')
    consopts.add_option('--without-tracklets', dest='without_tracklets', action='store_true')
    consopts.add_option('--with-opt-correct', dest='woptical', action='store_true')
    consopts.add_option('--det', dest='detection_weight', type='float', default=10.0,
                        help='detection weight [default: %default]')
    consopts.add_option('--div', dest='division_weight', type='float', default=10.0,
                        help='division weight [default: %default]')
    consopts.add_option('--dis', dest='disappearance_cost', type='float', default=500.0,
                        help='disappearance cost [default: %default]')
    consopts.add_option('--app', dest='appearance_cost', type='float', default=500.0,
                        help='appearance cost [default: %default]')
    consopts.add_option('--tr', dest='transition_weight', type='float', default=10.0,
                        help='transition weight [default: %default]')
    consopts.add_option('--motionModelWeight', dest='motionModelWeight', type='float', default=0.0,
                        help='motion model weight [default: %default]')
    consopts.add_option('--without-divisions', dest='without_divisions', action='store_true')
    consopts.add_option('--means', dest='means', type='float', default=0.0,
                        help='means for detection [default: %default]')
    consopts.add_option('--sigma', dest='sigma', type='float', default=0.0,
                        help='sigma for detection [default: %default]')
    consopts.add_option('--with-merger-resolution', dest='with_merger_resolution', action='store_true', default=False)
    consopts.add_option('--without-constraints', dest='woconstr', action='store_true', default=False)
    consopts.add_option('--trans-par', dest='trans_par', type='float', default=5.0,
                        help='alpha for the transition prior [default: %default]')
    consopts.add_option('--border-width', dest='border_width', type='float', default=0.0,
                        help='absolute border margin in which the appearance/disappearance costs are linearly decreased [default: %default]')
    consopts.add_option('--ext-probs', dest='ext_probs', type='string', default=None,
                        help='provide a path to hdf5 files containing detection probabilities [default:%default]')
    consopts.add_option('--objCountPath', dest='obj_count_path', type='string',
                        default='/CountClassification/Probabilities/0/',
                        help='internal hdf5 path to object count probabilities [default=%default]')
    consopts.add_option('--objCountFile', dest='obj_count_file', type='string', default=None,
                        help='Filename of the HDF file containing the object count classifier. If None, will be taken from ILP [default=%default]')
    consopts.add_option('--divPath', dest='div_prob_path', type='string', default='/DivisionDetection/Probabilities/0/',
                        help='internal hdf5 path to division probabilities [default=%default]')
    consopts.add_option('--divFile', dest='div_file', type='string', default=None,
                        help='Filename of the HDF file containing the division classifier. If None, will be taken from ILP [default=%default]')
    consopts.add_option('--featsPath', dest='feats_path', type='string',
                        default='/TrackingFeatureExtraction/RegionFeaturesVigra/0000/[[%d], [%d]]/Default features/%s',
                        help='internal hdf5 path to object features [default=%default]')
    consopts.add_option('--translationPath', dest='trans_vector_path', type='str',
                        default='OpticalTranslation/TranslationVectors/0/data',
                        help='internal hdf5 path to translation vectors [default=%default]')
    consopts.add_option('--labelImgPath', dest='label_img_path', type='str',
                        default='/TrackingFeatureExtraction/LabelImage/0000/[[%d, 0, 0, 0, 0], [%d, %d, %d, %d, 1]]',
                        help='internal hdf5 path to label image [default=%default]')
    consopts.add_option('--timeout', dest='timeout', type='float', default=1e+75,
                        help='CPLEX timeout in sec. [default: %default]')
    consopts.add_option('--with-graph-labeling', dest='w_labeling', action='store_true', default=False,
                        help='load ground truth labeling into hypotheses graph for further evaluation on C++ side,\
                        requires gt-path to point to the groundtruth files')
    consopts.add_option('--transition-classifier-filename', dest='transition_classifier_filename', type='str',
                        default=None)
    consopts.add_option('--transition-classifier-path', dest='transition_classifier_path', type='str', default='/')

    parser.add_option_group(consopts)

    optcfg, args = parser.parse_args()

    if (optcfg.config != None):
        with open(optcfg.config) as f:
            configfilecommands = f.read().splitlines()
        optcfg, args2 = parser.parse_args(configfilecommands)

    numArgs = len(args)
    if numArgs == 0 or optcfg.json_filename == None:
        parser.print_help()
        sys.exit(1)

    return optcfg, args


def generate_traxelstore(h5file,
                         options,
                         feature_path,
                         time_range,
                         x_range,
                         y_range,
                         z_range,
                         size_range,
                         x_scale=1.0,
                         y_scale=1.0,
                         z_scale=1.0,
                         with_div=True,
                         with_local_centers=False,
                         median_object_size=None,
                         max_traxel_id_at=None,
                         with_merger_prior=True,
                         max_num_mergers=1,
                         with_optical_correction=False,
                         ext_probs=None
                         ):
    """
    Legacy way of creating the "traxelstore", that can handle the old drosophila and rapoport
    ilastik project files and load the stored probabilities.
    """

    logging.info("generating traxels")
    logging.info("filling traxelstore")
    import pgmlink as track
    ts = track.TraxelStore()
    fs = track.FeatureStore()
    max_traxel_id_at = track.VectorOfInt()

    logging.info("fetching region features and division probabilities")
    logging.debug("{}, {}".format(h5file.filename, feature_path))

    detection_probabilities = []
    division_probabilities = []

    if with_div:
        logging.debug(options.div_prob_path)
        divProbs = h5file[options.div_prob_path]

    if with_merger_prior:
        detProbs = h5file[options.obj_count_path]

    if with_local_centers:
        localCenters = None  # self.RegionLocalCenters(time_range).wait()

    if x_range is None:
        x_range = [0, sys.maxint]

    if y_range is None:
        y_range = [0, sys.maxint]

    if z_range is None:
        z_range = [0, sys.maxint]

    shape_t = len(h5file[options.obj_count_path].keys())
    keys_sorted = range(shape_t)

    if time_range is not None:
        if time_range[1] == -1:
            time_range[1] = shape_t
        keys_sorted = [key for key in keys_sorted if time_range[0] <= int(key) < time_range[1]]
    else:
        time_range = (0, shape_t)

    filtered_labels = {}
    obj_sizes = []
    total_count = 0
    empty_frame = False

    for t in keys_sorted:
        feats_name = options.feats_path % (t, t + 1, 'RegionCenter')
        # region_centers = np.array(feats[t]['0']['RegionCenter'])
        region_centers = np.array(h5file[feats_name])

        feats_name = options.feats_path % (t, t + 1, 'Coord<Minimum>')
        lower = np.array(h5file[feats_name])
        feats_name = options.feats_path % (t, t + 1, 'Coord<Maximum>')
        upper = np.array(h5file[feats_name])

        if region_centers.size:
            region_centers = region_centers[1:, ...]
            lower = lower[1:, ...]
            upper = upper[1:, ...]
        if with_optical_correction:
            try:
                feats_name = options.feats_path % (t, t + 1, 'RegionCenter_corr')
                region_centers_corr = np.array(h5file[feats_name])
            except:
                raise Exception, 'cannot consider optical correction since it has not been computed'
            if region_centers_corr.size:
                region_centers_corr = region_centers_corr[1:, ...]

        feats_name = options.feats_path % (t, t + 1, 'Count')
        # pixel_count = np.array(feats[t]['0']['Count'])
        pixel_count = np.array(h5file[feats_name])
        if pixel_count.size:
            pixel_count = pixel_count[1:, ...]

        logging.info("at timestep {}, {} traxels found".format(t, region_centers.shape[0]))
        count = 0
        filtered_labels[t] = []
        for idx in range(region_centers.shape[0]):
            if len(region_centers[idx]) == 2:
                x, y = region_centers[idx]
                z = 0
            elif len(region_centers[idx]) == 3:
                x, y, z = region_centers[idx]
            else:
                raise Exception, "The RegionCenter feature must have dimensionality 2 or 3."
            size = pixel_count[idx]
            if (x < x_range[0] or x >= x_range[1] or
                        y < y_range[0] or y >= y_range[1] or
                        z < z_range[0] or z >= z_range[1] or
                        size < size_range[0] or size >= size_range[1]):
                filtered_labels[t].append(int(idx + 1))
                continue
            else:
                count += 1
            traxel = track.Traxel()
            traxel.set_feature_store(fs)
            traxel.set_x_scale(x_scale)
            traxel.set_y_scale(y_scale)
            traxel.set_z_scale(z_scale)
            traxel.Id = int(idx + 1)
            traxel.Timestep = int(t)

            traxel.add_feature_array("com", 3)
            for i, v in enumerate([x, y, z]):
                traxel.set_feature_value('com', i, float(v))

            if with_optical_correction:
                traxel.add_feature_array("com_corrected", 3)
                for i, v in enumerate(region_centers_corr[idx]):
                    traxel.set_feature_value("com_corrected", i, float(v))
                if len(region_centers_corr[idx]) == 2:
                    traxel.set_feature_value("com_corrected", 2, 0.)

            if with_div:
                traxel.add_feature_array("divProb", 1)
                prob = 0.0

                prob = float(divProbs[str(t)][idx + 1][1])
                # idx+1 because region_centers and pixel_count start from 1, divProbs starts from 0
                traxel.set_feature_value("divProb", 0, prob)
                division_probabilities.append(prob)

            if with_local_centers:
                raise Exception, "not yet implemented"
                traxel.add_feature_array("localCentersX", len(localCenters[t][idx + 1]))
                traxel.add_feature_array("localCentersY", len(localCenters[t][idx + 1]))
                traxel.add_feature_array("localCentersZ", len(localCenters[t][idx + 1]))
                for i, v in enumerate(localCenters[t][idx + 1]):
                    traxel.set_feature_value("localCentersX", i, float(v[0]))
                    traxel.set_feature_value("localCentersY", i, float(v[1]))
                    traxel.set_feature_value("localCentersZ", i, float(v[2]))

            if with_merger_prior and ext_probs is None:
                traxel.add_feature_array("detProb", max_num_mergers + 1)
                probs = []
                for i in range(len(detProbs[str(t)][idx + 1])):
                    probs.append(float(detProbs[str(t)][idx + 1][i]))
                probs[max_num_mergers] = sum(probs[max_num_mergers:])
                for i in range(max_num_mergers + 1):
                    traxel.set_feature_value("detProb", i, float(probs[i]))

            detection_probabilities.append([traxel.get_feature_value("detProb", i) for i in range(max_num_mergers + 1)])

            traxel.add_feature_array("count", 1)
            traxel.set_feature_value("count", 0, float(size))
            if median_object_size is not None:
                obj_sizes.append(float(size))
            ts.add(fs, traxel)

        logging.info("at timestep {}, {} traxels passed filter".format(t, count))
        max_traxel_id_at.append(int(region_centers.shape[0]))
        if count == 0:
            empty_frame = True

        total_count += count

    if median_object_size is not None:
        median_object_size[0] = np.median(np.array(obj_sizes), overwrite_input=True)
        logging.info('median object size = {}'.format(median_object_size[0]))

    return ts, fs, max_traxel_id_at, division_probabilities, detection_probabilities


def getH5Dataset(h5group, ds_name):
    if ds_name in h5group.keys():
        return np.array(h5group[ds_name])

    return np.array([])


def getRegionFeatures(ndim):
    region_features = [
        ("RegionCenter", ndim),
        ("Count", 1),
        ("Variance", 1),
        ("Sum", 1),
        ("Mean", 1),
        ("RegionRadii", ndim),
        ("Central< PowerSum<2> >", 1),
        ("Central< PowerSum<3> >", 1),
        ("Central< PowerSum<4> >", 1),
        ("Kurtosis", 1),
        ("Maximum", 1),
        ("Minimum", 1),
        ("RegionAxes", ndim ** 2),
        ("Skewness", 1),
        ("Weighted<PowerSum<0> >", 1),
        ("Coord< Minimum >", ndim),
        ("Coord< Maximum >", ndim)
    ]
    return region_features


def getTraxelStore(options, ilp_fn, time_range, shape):
    max_traxel_id_at = []
    with h5py.File(ilp_fn, 'r') as h5file:
        ndim = 3

        logging.debug('/'.join(options.label_img_path.strip('/').split('/')[:-1]))

        if h5file['/'.join(options.label_img_path.strip('/').split('/')[:-1])].values()[0].shape[3] == 1:
            ndim = 2
        logging.debug('ndim={}'.format(ndim))

        logging.info("Time Range: {}".format(time_range))
        if options.load_traxelstore:
            logging.info('loading traxelstore from file')
            import pickle

            with open(options.load_traxelstore, 'rb') as ts_in:
                ts = pickle.load(ts_in)
                fs = pickle.load(ts_in)
                max_traxel_id_at = pickle.load(ts_in)
                ts.set_feature_store(fs)

            info = [int(x) for x in ts.bounding_box()]
            t0, t1 = (info[0], info[4])
            if info[0] != options.mints or (options.maxts != -1 and info[4] != options.maxts - 1):
                if options.maxts == -1:
                    options.maxts = info[4] + 1
                logging.warning("Traxelstore has different time range than requested FOV. Trimming traxels...")
                fov = getFovFromOptions(options, shape, t0, t1)
                fov.set_time_bounds(options.mints, options.maxts - 1)
                new_ts = track.TraxelStore()
                ts.filter_by_fov(new_ts, fov)
                ts = new_ts
        else:
            max_num_mer = int(options.max_num_objects)
            ts, fs, max_traxel_id_at, division_probabilities, detection_probabilities = generate_traxelstore(
                h5file=h5file,
                options=options,
                feature_path=feature_path,
                time_range=time_range,
                x_range=None,
                y_range=None,
                z_range=None,
                size_range=[options.minsize, options.maxsize],
                x_scale=options.x_scale,
                y_scale=options.y_scale,
                z_scale=options.z_scale,
                with_div=with_div,
                with_local_centers=False,
                median_object_size=obj_size,
                max_traxel_id_at=max_traxel_id_at,
                with_merger_prior=with_merger_prior,
                max_num_mergers=max_num_mer,
                with_optical_correction=bool(options.woptical),
                ext_probs=options.ext_probs
                )

        info = [int(x) for x in ts.bounding_box()]
        t0, t1 = (info[0], info[4])
        logging.info("-> Traxelstore bounding box: " + str(info))

        if options.dump_traxelstore:
            logging.info('dumping traxelstore to file')
            import pickle

            with open(options.dump_traxelstore, 'wb') as ts_out:
                pickle.dump(ts, ts_out)
                pickle.dump(fs, ts_out)
                pickle.dump(max_traxel_id_at, ts_out)

    return ts, fs, max_traxel_id_at, ndim, t0, t1


def getFovFromOptions(options, shape, t0, t1):
    import pgmlink as track
    [xshape, yshape, zshape] = shape

    fov = track.FieldOfView(t0, 0, 0, 0, t1, options.x_scale * (xshape - 1), options.y_scale * (yshape - 1),
                            options.z_scale * (zshape - 1))
    return fov


def getPythonFovFromOptions(options, shape, t0, t1):
    from fieldofview import FieldOfView
    [xshape, yshape, zshape] = shape

    fov = FieldOfView(t0, 0, 0, 0, t1, options.x_scale * (xshape - 1), options.y_scale * (yshape - 1),
                      options.z_scale * (zshape - 1))
    return fov


def initializeConservationTracking(options, shape, t0, t1):
    import pgmlink as track
    ndim = 2 if shape[-1] == 1 else 3
    rf_fn = 'none'
    if options.rf_fn:
        rf_fn = options.rf_fn

    fov = getFovFromOptions(options, shape, t0, t1)
    if ndim == 2:
        [xshape, yshape, zshape] = shape
        assert options.z_scale * (zshape - 1) == 0, "fov of z must be (0,0) if ndim == 2"

    if options.method == 'conservation':
        tracker = track.ConsTracking(int(options.max_num_objects),
                                     bool(options.size_dependent_detection_prob),
                                     options.avg_obj_size[0],
                                     options.mnd,
                                     not bool(options.without_divisions),
                                     options.division_threshold,
                                     rf_fn,
                                     fov,
                                     "none",
                                     track.ConsTrackingSolverType.CplexSolver)
    elif options.method == 'conservation-dynprog':
        tracker = track.ConsTracking(int(options.max_num_objects),
                                     bool(options.size_dependent_detection_prob),
                                     options.avg_obj_size[0],
                                     options.mnd,
                                     not bool(options.without_divisions),
                                     options.division_threshold,
                                     rf_fn,
                                     fov,
                                     "none",
                                     track.ConsTrackingSolverType.DynProgSolver)
    else:
        raise InvalidArgumentException("Must be conservation or conservation-dynprog")
    return tracker, fov


def loadPyTraxelstore(options,
                      ilpFilename,
                      objectCountClassifierPath=None,
                      divisionClassifierPath=None,
                      time_range=None,
                      usePgmlink=True):
    """
    Set up a python side traxel store: compute all features, but do not evaluate classifiers.
    """
    import traxelstore
    ilpOptions = traxelstore.IlastikProjectOptions()
    ilpOptions.objectCountClassifierPath = objectCountClassifierPath
    ilpOptions.divisionClassifierPath = divisionClassifierPath
    ilpOptions.labelImagePath = options.label_img_path
    ilpOptions.rawImagePath = options.raw_path
    ilpOptions.rawImageFilename = options.raw_filename
    ilpOptions.sizeFilter = [options.minsize, options.maxsize]
    if options.label_image_file is not None:
        ilpOptions.labelImageFilename = options.label_image_file
    else:
        ilpOptions.labelImageFilename = ilpFilename

    if options.obj_count_file != None:
        ilpOptions.objectCountClassifierFilename = options.obj_count_file
    else:
        ilpOptions.objectCountClassifierFilename = ilpFilename

    if options.div_file != None:
        ilpOptions.divisionClassifierFilename = options.div_file
    else:
        ilpOptions.divisionClassifierFilename = ilpFilename

    pyTraxelstore = traxelstore.Traxelstore(ilpOptions)
    if time_range is not None:
        pyTraxelstore.timeRange = time_range
    a = pyTraxelstore.fillTraxelStore(usePgmlink=usePgmlink)
    if usePgmlink:
        t, f = a
    else:
        t = None
        f = None
    return pyTraxelstore, t, f


def loadTransitionClassifier(transitionClassifierFilename, transitionClassifierPath):
    """
    Load a transition classifier random forest from a HDF5 file
    """
    import traxelstore
    rf = traxelstore.RandomForestClassifier(transitionClassifierPath, transitionClassifierFilename)
    return rf


def negLog(features):
    fa = np.array(features)
    fa[fa < 0.0000000001] = 0.0000000001
    return list(np.log(fa) * -1.0)


def getDetectionFeatures(traxel, max_state):
    return hypothesesgraph.getTraxelFeatureVector(traxel, "detProb", max_state)


def getDivisionFeatures(traxel):
    prob = traxel.get_feature_value("divProb", 0)
    return [1.0 - prob, prob]


def getTransitionFeaturesDist(traxelA, traxelB, transitionParam, max_state):
    """
    Get the transition probabilities based on the object's distance
    """
    positions = [np.array([t.X(), t.Y(), t.Z()]) for t in [traxelA, traxelB]]
    dist = np.linalg.norm(positions[0] - positions[1])
    prob = np.exp(-dist / transitionParam)
    return [1.0 - prob] + [prob] * (max_state - 1)


def getTransitionFeaturesRF(traxelA, traxelB, transitionClassifier, pyTraxelstore, max_state):
    """
    Get the transition probabilities by predicting them with the classifier
    """
    feats = [pyTraxelstore.getTraxelFeatureDict(obj.Timestep, obj.Id) for obj in [traxelA, traxelB]]
    featVec = pyTraxelstore.getTransitionFeatureVector(feats[0], feats[1], transitionClassifier.selectedFeatures)
    probs = transitionClassifier.predictProbabilities(featVec)[0]
    return [probs[0]] + [probs[1]] * (max_state - 1)


def getBoundaryCostMultiplier(traxel, fov, margin):
    dist = fov.spatial_distance_to_border(traxel.Timestep, traxel.X(), traxel.Y(), traxel.Z(), False)
    if dist > margin:
        return 1.0
    else:
        if margin > 0:
            return float(dist) / margin
        else:
            return 1.0


def listify(l):
    return [[e] for e in l]


def getHypothesesGraphAndIterators(options, shape, t0, t1, ts, pyTraxelstore):
    """
    Build the hypotheses graph either using pgmlink, or from the python traxelstore in python
    """
    if pyTraxelstore is not None:
        logging.info("Building python hypotheses graph")
        hypotheses_graph = hypothesesgraph.HypothesesGraph()
        hypotheses_graph.buildFromTraxelstore(pyTraxelstore,
                                              numNearestNeighbors=options.max_nearest_neighbors,
                                              maxNeighborDist=options.mnd,
                                              withDivisions=not options.without_divisions,
                                              divisionThreshold=options.division_threshold)

        # TODO:
        # if not options.without_tracklets:
        #       hypotheses_graph.generateTrackletGraph()

        n_it = hypotheses_graph.nodeIterator()
        a_it = hypotheses_graph.arcIterator()
        fov = getPythonFovFromOptions(options, shape, t0, t1)

    else:
        import pgmlink as track
        logging.info("Building pgmlink hypotheses graph")
        # initialize tracker to get hypotheses graph
        tracker, fov = initializeConservationTracking(options, shape, t0, t1)
        hypotheses_graph = tracker.buildGraph(ts, options.max_nearest_neighbors)

        # create tracklet graph if necessary
        if not options.without_tracklets:
            traxel_graph = hypotheses_graph
            hypotheses_graph = traxel_graph.generate_tracklet_graph()

        n_it = track.NodeIt(hypotheses_graph)
        a_it = track.ArcIt(hypotheses_graph)

    return hypotheses_graph, n_it, a_it, fov


def loadTraxelstoreAndTransitionClassifier(options, ilp_fn, time_range, shape):
    """
    Load traxelstore either from ilp or by computing raw features, 
    loading random forests, and predicting for each object.
    Also load the transition classifier if raw features were computed and a transitionClassifierFile is given
    """
    transitionClassifier = None

    try:
        ts, fs, _, ndim, t0, t1 = getTraxelStore(options, ilp_fn, time_range, shape)
        foundDetectionProbabilities = True
    except Exception as e:
        print(e)
        foundDetectionProbabilities = False
        logging.warning("could not load detection (and/or division) probabilities from ilastik project file")

    if options.raw_filename != None:
        if foundDetectionProbabilities:
            pyTraxelstore, _, _ = loadPyTraxelstore(options, ilp_fn, time_range, usePgmlink=False)
        else:
            # warning: assuming that the classifiers are top-level groups in HDF5
            objectCountClassifierPath = '/' + [t for t in options.obj_count_path.split('/') if len(t) > 0][0]
            if not options.without_divisions:
                divisionClassifierPath = '/' + [t for t in options.div_prob_path.split('/') if len(t) > 0][0]
            else:
                divisionClassifierPath = None
            pyTraxelstore, ts, fs = loadPyTraxelstore(options,
                                                      ilp_fn,
                                                      objectCountClassifierPath=objectCountClassifierPath,
                                                      divisionClassifierPath=divisionClassifierPath,
                                                      time_range=time_range,
                                                      usePgmlink=False)
            t0, t1 = pyTraxelstore.timeRange
            ndim = pyTraxelstore.getNumDimensions()
            foundDetectionProbabilities = True

        if options.transition_classifier_filename != None:
            transitionClassifier = loadTransitionClassifier(options.transition_classifier_filename,
                                                            options.transition_classifier_path)
    else:
        pyTraxelstore = None

    assert (foundDetectionProbabilities)

    return ts, fs, ndim, t0, t1, pyTraxelstore, transitionClassifier


if __name__ == "__main__":
    """
    Main loop of script
    """
    logging.basicConfig(level=logging.INFO)
    options, args = getConfigAndCommandLineArguments()

    # get filenames
    numArgs = len(args)
    fns = []
    if numArgs > 0:
        for arg in args:
            logging.debug(arg)
            fns.extend(glob.glob(arg))
        fns.sort()
        logging.info(fns)

    ilp_fn = fns[0]

    # create output path if it doesn't exist
    if not path.exists(options.out_dir):
        try:
            os.makedirs(options.out_dir)
        except:
            pass

    # Do the tracking
    start = time.time()

    feature_path = options.feats_path
    with_div = not bool(options.without_divisions)
    with_merger_prior = True

    # get selected time range
    time_range = [options.mints, options.maxts]
    if options.maxts == -1 and options.mints == 0:
        time_range = None

    # set average object size if chosen
    obj_size = [0]
    if options.avg_obj_size != 0:
        obj_size[0] = options.avg_obj_size
    else:
        options.avg_obj_size = obj_size

    # find shape of dataset
    with h5py.File(ilp_fn, 'r') as h5file:
        shape = h5file['/'.join(options.label_img_path.split('/')[:-1])].values()[0].shape[1:4]

    # load traxelstore
    ts, fs, ndim, t0, t1, pyTraxelstore, transitionClassifier = loadTraxelstoreAndTransitionClassifier(options, ilp_fn,
                                                                                                       time_range,
                                                                                                       shape)

    # build hypotheses graph
    hypotheses_graph, n_it, a_it, fov = getHypothesesGraphAndIterators(options, shape, t0, t1, ts, pyTraxelstore)

    # prepare json output
    jsonRoot = {}
    traxelIdPerTimestepToUniqueIdMap = {}

    if pyTraxelstore is None:
        import pgmlink

        numElements = pgmlink.countNodes(hypotheses_graph) + pgmlink.countArcs(hypotheses_graph)
    else:
        numElements = hypotheses_graph.countNodes() + hypotheses_graph.countArcs()

    progressBar = ProgressBar(stop=numElements)
    maxNumObjects = int(options.max_num_objects) + 1  # because we need features for state 0 as well!
    margin = float(options.border_width)

    # get the map of node -> list(traxel) or just traxel
    if options.without_tracklets:
        traxelMap = hypotheses_graph.getNodeTraxelMap()
    else:
        traxelMap = hypotheses_graph.getNodeTrackletMap()

    # add all detections to JSON
    detections = []
    for i, n in enumerate(n_it):
        detection = {}
        if options.without_tracklets:
            # only one traxel, but make it a list so everything below works the same
            traxels = [traxelMap[n]]
        else:
            traxels = traxelMap[n]

        # store mapping of all contained traxels to this detection uuid
        for t in traxels:
            traxelIdPerTimestepToUniqueIdMap.setdefault(str(t.Timestep), {})[str(t.Id)] = i

        detection['id'] = i

        # accumulate features over all contained traxels
        previousTraxel = None
        detFeats = np.zeros(maxNumObjects)
        for t in traxels:
            detFeats += np.array(negLog(getDetectionFeatures(t, maxNumObjects)))
            if previousTraxel is not None:
                if transitionClassifier is None:
                    detFeats += np.array(
                        negLog(getTransitionFeaturesDist(previousTraxel, t, options.trans_par, maxNumObjects)))
                else:
                    detFeats += np.array(negLog(
                        getTransitionFeaturesRF(previousTraxel, t, transitionClassifier, pyTraxelstore, maxNumObjects)))
            previousTraxel = t

        detection['features'] = listify(list(detFeats))

        # division only if probability is big enough
        try:
            divFeats = getDivisionFeatures(traxels[-1])
            if divFeats[1] > options.division_threshold:
                detection['divisionFeatures'] = listify(negLog(divFeats))
        except:
            pass

        detection['timestep'] = [traxels[0].Timestep, traxels[-1].Timestep]

        if traxels[0].Timestep <= t0:
            detection['appearanceFeatures'] = listify([0.0] * (maxNumObjects))
        else:
            detection['appearanceFeatures'] = listify(
                [0.0] + [getBoundaryCostMultiplier(traxels[0], fov, margin)] * (maxNumObjects - 1))

        if traxels[-1].Timestep >= t1 - 1:
            detection['disappearanceFeatures'] = listify([0.0] * (maxNumObjects))
        else:
            detection['disappearanceFeatures'] = listify(
                [0.0] + [getBoundaryCostMultiplier(traxels[-1], fov, margin)] * (maxNumObjects - 1))

        detections.append(detection)
        progressBar.show()

    # add all links
    links = []
    for a in a_it:
        link = {}
        if options.without_tracklets:
            srcTraxel = traxelMap[hypotheses_graph.source(a)]
            destTraxel = traxelMap[hypotheses_graph.target(a)]
        else:
            srcTraxel = traxelMap[hypotheses_graph.source(a)][-1]  # src is last of the traxels in source tracklet
            destTraxel = traxelMap[hypotheses_graph.target(a)][0]  # dest is first of traxels in destination tracklet
        link['src'] = traxelIdPerTimestepToUniqueIdMap[str(srcTraxel.Timestep)][str(srcTraxel.Id)]
        link['dest'] = traxelIdPerTimestepToUniqueIdMap[str(destTraxel.Timestep)][str(destTraxel.Id)]
        if transitionClassifier is None:
            link['features'] = listify(
                negLog(getTransitionFeaturesDist(srcTraxel, destTraxel, options.trans_par, maxNumObjects)))
        else:
            link['features'] = listify(negLog(
                getTransitionFeaturesRF(srcTraxel, destTraxel, transitionClassifier, pyTraxelstore, maxNumObjects)))
        links.append(link)
        progressBar.show()

    # write everything to JSON
    settings = {}
    settings['statesShareWeights'] = True
    settings['allowPartialMergerAppearance'] = False
    settings['requireSeparateChildrenOfDivision'] = True
    settings['optimizerEpGap'] = 0.01
    settings['optimizerVerbose'] = True
    settings['optimizerNumThreads'] = 1

    jsonRoot['traxelToUniqueId'] = traxelIdPerTimestepToUniqueIdMap
    jsonRoot['segmentationHypotheses'] = detections
    jsonRoot['linkingHypotheses'] = links
    jsonRoot['settings'] = settings
    jsonRoot['exclusions'] = []

    with open(options.json_filename, 'w') as f:
        json.dump(jsonRoot, f, indent=4, separators=(',', ': '))
