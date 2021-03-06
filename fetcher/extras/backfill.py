from datetime import datetime
import csv
import numpy as np
import pandas as pd

from fetcher.extras.common import MaContextManager
from fetcher.utils import map_attributes, Fields, extract_arcgis_attributes


NULL_DATE = datetime(2020, 1, 1)
DATE = Fields.DATE.name
TS = Fields.TIMESTAMP.name


def make_cumsum_df(data, timestamp_field=Fields.TIMESTAMP.name):
    df = pd.DataFrame(data)
    df.set_index(timestamp_field, inplace=True)
    df.sort_index(inplace=True)
    df = df.select_dtypes(exclude=['string', 'object'])
    # .groupby(level=0).last() # can do it here, but not mandatory

    cumsum_df = df.cumsum()
    cumsum_df[Fields.TIMESTAMP.name] = cumsum_df.index
    return cumsum_df


def handle_ak(res, mapping):
    tests = res[0]
    collected = [x['attributes'] for x in tests['features']]
    df = pd.DataFrame(collected)
    df = df.pivot(columns='Test_Result', index='Date_Collected')
    df.columns = df.columns.droplevel()
    df['tests_total'] = df.sum(axis=1)

    df = df.rename(columns=mapping).cumsum()
    df[TS] = df.index

    tagged = df.to_dict(orient='records')
    return tagged


def handle_al(res, mapping):
    '''AL hospitalization has only month-day, need to fix it
    by adding the correct year (2020)'''
    mapped = []
    for result in res[:-1]:
        partial = extract_arcgis_attributes(result, mapping)
        mapped.extend(partial)

    cumsum_df = make_cumsum_df(mapped)
    mapped = cumsum_df.to_dict(orient='records')

    # fix funny dates
    mapping['__strptime'] = "%m-%d"
    partial = extract_arcgis_attributes(res[-1], mapping)
    for x in partial:
        d = x[DATE]
        ts = datetime.strptime(d+"-2020", "%m-%d-%Y")
        x[TS] = ts.timestamp()
    mapped.extend(partial)

    return mapped


def handle_ar(res, mapping):
    # simply a cumsum table
    data = extract_arcgis_attributes(res[0], mapping)
    cumsum_df = make_cumsum_df(data)
    return cumsum_df.to_dict(orient='records')


def handle_ct(res, mapping):
    tests = res[0]
    df = pd.DataFrame(tests).rename(columns=mapping).set_index(DATE)
    for c in df.columns:
        # convert to numeric
        df[c] = pd.to_numeric(df[c])

    df.index = df.index.fillna(NULL_DATE.strftime(mapping.get('__strptime')))
    df = df.sort_index().cumsum()
    df[TS] = pd.to_datetime(df.index)
    df[TS] = df[TS].values.astype(np.int64) // 10 ** 9
    return df.to_dict(orient='records')


def handle_ma(res, mapping):
    '''Returning a list of dictionaries (records)
    '''
    tagged = []
    # break the mapping to {file -> {mapping}}
    # not the most efficient, but the data is tiny
    file_mapping = {x.split(":")[0]: {} for x in mapping.keys() if x.find(':') > 0}
    for k, v in mapping.items():
        if k.find(':') < 0:
            continue
        filename, field = k.split(":")
        file_mapping[filename][field] = v

    with MaContextManager(res[0]) as zipdir:
        for filename in file_mapping.keys():
            with open("{}/{}".format(zipdir, filename), 'r') as csvfile:
                if filename == 'TestingByDate.csv':
                    # we need the cumsum of all columns
                    df = pd.read_csv(csvfile)
                    df = df.rename(columns=file_mapping.get(filename))[
                        file_mapping.get(filename).values()]
                    df[DATE] = pd.to_datetime(df[DATE])
                    df = df.set_index(DATE).cumsum()
                    df[DATE] = df.index.strftime(mapping.get('__strptime'))
                    tagged.extend(df.to_dict(orient='records'))
                    continue

                reader = csv.DictReader(csvfile, dialect='unix')
                rows = list(reader)
                tagged_rows = [map_attributes(r, file_mapping.get(filename), 'MA') for r in rows]
                tagged.extend(tagged_rows)

    return tagged


def handle_md(res, mapping):
    mapped = []
    for result in res[:-1]:
        partial = extract_arcgis_attributes(result, mapping, 'MD')
        mapped.extend(partial)

    # PCR positives
    testing = res[-1]
    testing = extract_arcgis_attributes(testing, mapping, 'MD')
    cumsum_df = make_cumsum_df(testing)
    mapped.extend(cumsum_df.to_dict(orient='records'))
    return mapped


def handle_mo(res, mapping):
    # we're getting pretty good data that we need to cumsum
    # TODO: this can be done elsewhere/by te lib, if there are other use cases
    mapped = []
    for result in res:
        partial = extract_arcgis_attributes(result, mapping, 'MO')
        mapped.extend(partial)

    # expect the data to be sorted, because the query sorts it
    # somewhat funny here with building a DF and instantly breaking it
    cumsum_df = make_cumsum_df(mapped)
    cumsum_df[Fields.FETCH_TIMESTAMP.name] = datetime.now()
    return cumsum_df.to_dict('records')


def handle_nd(res, mapping):
    # simply a cumsum table
    res = res[0]
    res = res.rename(columns=mapping).set_index('DATE')
    res = res.cumsum()
    res['DATE'] = res.index
    res = res[[v for k, v in mapping.items() if k != '__strptime']]
    records = res.to_dict(orient='records')
    return records


def handle_ri(res, mapping):
    res = res[0]
    res = res.rename(columns=mapping)
    res = res[[v for k, v in mapping.items() if k != '__strptime']]
    # TODO: consider working with DFs directly
    records = res.to_dict(orient='records')
    return records


def handle_va(res, mapping):
    tests = res[0]
    df = pd.DataFrame(tests).rename(columns=mapping).set_index(DATE)
    for c in df.columns:
        # convert to numeric
        df[c] = pd.to_numeric(df[c])

    df.index = pd.to_datetime(df.index, errors='coerce', format=mapping.get('__strptime'))
    df.index = df.index.fillna(NULL_DATE)
    df = df.sort_index().cumsum()
    df[TS] = pd.to_datetime(df.index)
    df[TS] = df[TS].values.astype(np.int64) // 10 ** 9
    return df.to_dict(orient='records')
