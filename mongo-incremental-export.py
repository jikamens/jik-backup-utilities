#!/usr/bin/env python3

from bson import BSON, ObjectId
import hashlib
import os
import pickle
from pymongo import MongoClient
import sys

levels = 7


def collection_file(db_name, collection_name, file_name, levels=0):
    components = [db_name, collection_name]
    if levels:
        characters = list(file_name if levels > 0 else reversed(file_name))
        components.extend(characters[0:abs(levels)])
    dir_name = os.path.join(*components)
    if not os.path.exists(dir_name):
        os.makedirs(dir_name)
    return os.path.join(dir_name, file_name)


def export(db, db_name, collection_name):
    collection = db[collection_name]
    checksums_path = collection_file(db_name, collection_name, 'checksums')
    try:
        checksums = pickle.load(open(checksums_path, 'rb'))
    except Exception:
        checksums = dict()
    new_checksums = dict()
    for doc in collection.find():
        bson = BSON.encode(doc)
        md5 = hashlib.md5(bson)
        new_checksum = md5.digest()
        _id = doc.get('_id', None)
        if not isinstance(_id, ObjectId):
            _id = md5.hexdigest()
        new_checksums[_id] = new_checksum
        if _id in checksums and checksums[_id] == new_checksum:
            # print(u'Skipping {}/{}'.format(collection_name, _id))
            continue
        print(u'Saving {}/{}'.format(collection_name, _id))
        with open(collection_file(
                db_name, collection_name, str(_id), -levels), 'wb') as f:
            f.write(bson)
    for _id in checksums:
        if _id not in new_checksums:
            print(u'Deleting {}/{}'.format(collection_name, _id))
            os.unlink(collection_file(
                db_name, collection_name, str(_id), -levels))
    with open(checksums_path, 'wb') as f:
        pickle.dump(new_checksums, f)


def main():
    for uri in sys.argv[1:]:
        db_name = uri.rsplit('/', 1)[-1]
        client = MongoClient(sys.argv[1])
        db = client[db_name]

        for collection_name in db.collection_names():
            export(db, db_name, collection_name)


if __name__ == '__main__':
    main()
