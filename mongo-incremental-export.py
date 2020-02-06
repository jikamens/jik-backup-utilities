#!/usr/bin/env python3

import argparse
from bson import BSON, ObjectId
from bson.codec_options import CodecOptions
from bson.son import SON
import hashlib
import os
import pickle
from pymongo import MongoClient

levels = 7
codec_options = CodecOptions(document_class=SON)


def collection_file(db_name, collection_name, file_name, levels=0):
    components = [db_name, collection_name]
    if levels:
        characters = list(file_name if levels > 0 else reversed(file_name))
        components.extend(characters[0:abs(levels)])
    dir_name = os.path.join(*components)
    if not os.path.exists(dir_name):
        os.makedirs(dir_name)
    return os.path.join(dir_name, file_name)


def export(db, db_name, collection_name, verbose=0):
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
        if _id in checksums:
            if checksums[_id] == new_checksum:
                if verbose > 1:
                    print(u'Skipping {}/{}'.format(collection_name, _id))
                continue
            if verbose > 0:
                print(u'Saving {}/{} (modified)'.format(collection_name, _id))
        else:
            if verbose > 0:
                print(u'Saving {}/{} (new)'.format(collection_name, _id))
        with open(collection_file(
                db_name, collection_name, str(_id), -levels), 'wb') as f:
            f.write(bson)
    for _id in checksums:
        if _id not in new_checksums:
            if verbose > 0:
                print(u'Deleting {}/{}'.format(collection_name, _id))
            os.unlink(collection_file(
                db_name, collection_name, str(_id), -levels))
    with open(checksums_path, 'wb') as f:
        pickle.dump(new_checksums, f)


def parse_args():
    parser = argparse.ArgumentParser(
        description='Export new and modified documents in a database into '
        'the current directory')
    parser.add_argument('--verbose', action='count', default=0,
                        help='Once prints messages for saved and deleted '
                        'documents, twice also prints for skipped documents')
    parser.add_argument('db_url', nargs='+', help='mongodb:// URLs of '
                        'databases to export')
    return parser.parse_args()


def main():
    args = parse_args()
    for uri in args.db_url:
        db_name = uri.rsplit('/', 1)[-1]
        client = MongoClient(uri, document_class=SON)
        db = client[db_name]

        for collection_name in db.collection_names():
            export(db, db_name, collection_name, verbose=args.verbose)


if __name__ == '__main__':
    main()
