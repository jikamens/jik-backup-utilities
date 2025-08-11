#!/usr/bin/env python3

import argparse
from bson import BSON, ObjectId
from bson.codec_options import CodecOptions
from bson.son import SON
import hashlib
import os
import pickle
import pymongo

levels = 3
codec_options = CodecOptions(document_class=SON)


def collection_dir(db_name, collection_name):
    return os.path.join(db_name, collection_name)


def collection_file(db_name, collection_name, file_name, levels=0):
    components = [db_name, collection_name]
    if levels:
        characters = list(file_name if levels > 0 else reversed(file_name))
        components.extend(characters[0:abs(levels)])
    dir_name = os.path.join(*components)
    if not os.path.exists(dir_name):
        os.makedirs(dir_name)
    return os.path.join(dir_name, file_name)


def export(args, db, db_name, collection_name):
    verbose = args.verbose
    dryrun = args.dryrun
    repair = args.repair
    check_dirs = set()
    collection = db[collection_name]
    checksums_path = collection_file(db_name, collection_name, 'checksums')
    try:
        checksums = pickle.load(open(checksums_path, 'rb'))
    except Exception:
        checksums = dict()
    new_checksums = dict()
    for doc in collection.find():
        bson = BSON.encode(doc, codec_options=codec_options)
        md5 = hashlib.md5(bson)
        new_checksum = md5.digest()
        _id = doc.get('_id', None)
        if not isinstance(_id, ObjectId):
            _id = md5.hexdigest()
        new_checksums[_id] = new_checksum
        action = None
        target_file = collection_file(
            db_name, collection_name, str(_id), -levels)
        if _id not in checksums:
            action = 'new'
        elif checksums[_id] != new_checksum:
            action = 'modified'
        if action is None and repair > 0:
            if not os.path.exists(target_file):
                action = 'missing'
        if action is None and repair > 1:
            old_checksum = hashlib.md5(open(target_file, 'rb').read()).digest()
            if new_checksum != old_checksum:
                action = 'corrupt'
        if action is None:
            if verbose > 1:
                print(u'Skipping {}/{}'.format(collection_name, _id))
            continue
        if verbose > 0:
            print(f'Saving {collection_name}/{_id} ({action})')
        if not dryrun:
            with open(target_file, 'wb') as f:
                f.write(bson)
    for _id in checksums:
        if _id not in new_checksums:
            target_file = collection_file(
                db_name, collection_name, str(_id), -levels)
            if repair > 0:
                if not os.path.exists(target_file):
                    continue
            if verbose > 0:
                print(u'Deleting {}/{}'.format(collection_name, _id))
            if not dryrun:
                os.unlink(target_file)
                check_dirs.add(os.path.dirname(target_file))
    if repair > 0:
        extra = []
        str_checksums = [str(_id) for _id in new_checksums]
        for dirpath, dirnames, filenames in os.walk(
                collection_dir(db_name, collection_name)):
            for filename in filenames:
                if filename == 'checksums':
                    continue
                if filename not in str_checksums:
                    filepath = os.path.join(dirpath, filename)
                    if verbose > 0:
                        print(f'Deleting {filepath} (extra)')
                    extra.append(filepath)
        if extra and not dryrun:
            for path in extra:
                os.unlink(path)
                check_dirs.add(os.path.dirname(path))
    if check_dirs and not dryrun:
        for directory in check_dirs:
            try:
                os.removedirs(directory)
            except OSError:
                pass
            else:
                if verbose > 0:
                    print(f'Removed {directory} (empty)')
    if not dryrun:
        with open(checksums_path, 'wb') as f:
            pickle.dump(new_checksums, f)


def parse_args():
    parser = argparse.ArgumentParser(
        description='Export new and modified documents in a database into '
        'the current directory')
    parser.add_argument('--verbose', action='count', default=0,
                        help='Once prints messages for saved and deleted '
                        'documents, twice also prints for skipped documents')
    parser.add_argument('--dryrun', '--dry-run', action='store_true',
                        default=False, help="Don't actually change anything")
    parser.add_argument('--repair', action='count', default=0,
                        help='Sanity-check export and repair missing / extra '
                        'files (specify twice to also confirm checksums)')
    parser.add_argument('db_url', nargs='+', help='mongodb:// URLs of '
                        'databases to export')
    return parser.parse_args()


def main():
    args = parse_args()
    for uri in args.db_url:
        db_name = pymongo.uri_parser.parse_uri(uri)['database']
        client = pymongo.MongoClient(uri, document_class=SON)
        db = client[db_name]

        for collection_name in db.list_collection_names():
            export(args, db, db_name, collection_name)


if __name__ == '__main__':
    main()
