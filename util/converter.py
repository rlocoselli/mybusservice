def rowConverter (rows,row_headers) :
    json_data=[]
    for result in rows:
        json_data.append(dict(zip(row_headers,result)))

    return json_data