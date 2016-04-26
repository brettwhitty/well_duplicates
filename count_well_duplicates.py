#!/usr/bin/env python

from __future__ import division, print_function, absolute_import
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
import sys


import logging
import Levenshtein
import bcl_direct_reader
from target import load_targets

DEF_SEQ = HIGHSEQ_4000 = "hiseq_4000"
HIGHSEQ_X = "hiseq_x"


def get_edit_distance(str1, str2):
    return Levenshtein.distance(str1, str2)


def get_hamming_distance(str1, str2):
    return Levenshtein.hamming(str1, str2)


def output_writer(lane, tile_dupl, levels):
    sys.stdout.write("Current lane: %s\n"%lane)
    l_tally = [0] * (levels + 1)
    l_length = [0] * (levels + 1)

    for tile in tile_dupl.keys():
        sys.stdout.write("Tile %s\n" % tile)
        levels_tally = 0
        levels_length = 0
        for level in range(1, levels+1):
            # {'1208': [ {'length': 0, 'tally': 0},
            #            {'length': 5989, 'tally': 181},
            #            {'length': 11966, 'tally': 335},
            #            {'length': 17939, 'tally': 509} ]}
            t_tally = tile_dupl[tile][level]['tally']
            l_tally[level] += t_tally
            levels_tally += t_tally
            t_length = tile_dupl[tile][level]['length']
            l_length[level] += t_length
            levels_length = t_length
            perc_dup = t_tally / t_length * 100
            perc_dup_cum = levels_tally / levels_length * 100
            sys.stdout.write("Level %s: %s\tcumulative: %s\n" %
                                (level, perc_dup,       perc_dup_cum))
    sys.stdout.write("Lane %s\n" % lane)
    cum_tally = 0
    cum_length = 0
    for level in range(1,levels+1):
        cum_tally += l_tally[level]
        cum_length = l_length[level]
        perc_dup = l_tally[level] / l_length[level] * 100
        perc_dup_cum = cum_tally / cum_length * 100
        sys.stdout.write("Level %s: %s\tcumulative: %s\n" % (level, perc_dup, perc_dup_cum))


def main():
    # Setup options
    optparser = _prepare_argparser()
    args = optparser.parse_args()
    # verify options
    arg_pass = _verify_option(args)
    if not arg_pass:
        logging.critical("Non valid arguments: exit")
        sys.exit(1)

    lanes = range(1, 8)
    if args.lane:
        lanes = args.lane.split(',')

    tiles = []
    max_tile = 0
    if args.stype == HIGHSEQ_4000:
        max_tile = 28
    else:
        max_tile = 24

    if args.tile_id:
        tiles = args.tile_id.split(',')
    else:
        for swath in [11, 12, 21, 22]:
            for tile in range(1, max_tile):  # should be 24 for hiseq_X
                tile_id = "%s%02d" % (swath, tile)
                tiles.append(tile_id)

    targets = load_targets(args.coord_file, args.level+1)
    bcl_reader = bcl_direct_reader.BCLReader(args.run)

    for lane in lanes:
        # dict[tile]
        tile_dupl = {}
        for tile in tiles:
            tile_bcl = bcl_reader.get_tile(lane, tile)
            seq_obj = tile_bcl.get_seqs(targets.get_all_indices(), args.start, args.end)

            # Initialise tally and length counters for this tile
            tile_dupl[tile] = [{'tally': 0, 'length': 0} for level in range(0, args.level+1)]
            target_counter = 0
            for target in targets.get_all_targets():
                target_counter += 1
                if target_counter >= args.sample_size:
                    break
                center = target.get_centre()
                #sys.stderr.write("Center: %s\n"%center)

                # if the center sequence does not pass the pass filter we don't assess edit distance
                # as large number of Ns compared to other reads with large number of Ns results in
                # small edit distance
                if not seq_obj[center][1]:
                    continue
                center_seq = seq_obj[center][0]

                for level in range(1, args.level+1):
                    l_dupl = []
                    assert(target.get_levels()>= level)
                    for well_index in target.get_indices(level):
                        well_seq = seq_obj[well_index][0]
                        dist = get_edit_distance(center_seq, well_seq)

                        if dist <= args.edit_distance:
                            l_dupl.append(1)
                            sys.stderr.write("Center seq: %s\n"%center_seq)
                            sys.stderr.write("well seq: %s\n"%well_seq)
                            sys.stderr.write("edit distance: %s\n"%dist)
                        else:
                            l_dupl.append(0)
                    if sum(l_dupl)>=1:
                        tile_dupl[tile][level]['tally'] += 1
                    tile_dupl[tile][level]['length'] += 1
                    #tile_dupl[tile][level]['tally'] += sum(l_dupl)
                    #tile_dupl[tile][level]['length'] += len(l_dupl)
            sys.stderr.write(str(tile_dupl))
        output_writer(lane, tile_dupl, args.level)


def _prepare_argparser():
    """Prepare optparser object. New options will be added in this
    function first.
    """
    usage = """usage: %prog <-f coord_file> [-e edit_distance -n sample_size -l level]"""
    description = """This script creates or executes commands that will assess well duplicates
    in a run without mapping. Reads within level l of a selected reads from the coordinate file
    will be assessed for Levenshtein (edit) distance.
    """

    prog_version = "0.1"
    parser = ArgumentParser(description=description, formatter_class=ArgumentDefaultsHelpFormatter)
    parser.add_argument("-f", "--coord_file", dest="coord_file", type=str,
                        help="The file containing the random sample per tile.")
    parser.add_argument("-e", "--edit_distance", dest="edit_distance", type=int, default=2,
                        help="max edit distance between two reads to count as duplicate")
    parser.add_argument("-n", "--sample_size", dest="sample_size", type=int, default=2500,
                        help="number of reads to be tested for well duplicates (max number" +
                             " of prepared clusters is 10000 at the moment)")
    parser.add_argument("-l", "--level", dest="level", type=int, default=3,
                        help="levels around central spot to test, max = 3")
    parser.add_argument("-s", "--stype", dest="stype", type=str,
                        help="Sequencer model, must be one of highseq_4000 or highseq_x")
    parser.add_argument("-r", "--run", dest="run", type=str,
                        help="path to base of run, i.e /ifs/seqdata/150715_K00169_0016_BH3FGFBBXX")
    parser.add_argument("-t", "--tile", dest="tile_id", type=str,
                        help="specific tile on a lane to analyse, four digits, follow Illumina tile numbering")
    parser.add_argument("-i", "--lane", dest="lane", type=str,
                        help="specific lane to analyse, 1-8")
    parser.add_argument("-x", "--start", dest="start", type=int, default=50,
                        help="Starting base position for the slice of read to be examined")
    parser.add_argument("-y", "--end", dest="end", type=int, default=100,
                        help="Final base position for the slice of read to be examined")

    return parser


def _verify_option(options):
    """Check if the mandatory option are present in the options objects.
    @return False if any argument is wrong."""
    arg_pass = True

    if not options.coord_file:
        logging.error("You must specify a coordinates file.")
        arg_pass = False
    if not options.run:
        logging.error("You must specify a run folder")
        arg_pass = False
    if (not options.stype) or (options.stype not in [HIGHSEQ_4000, HIGHSEQ_X]):
        logging.error("You must specify a sequencer model")
        arg_pass = False
    return arg_pass


if __name__ == "__main__":
    main()