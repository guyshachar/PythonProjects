def listToDictionary(list):
    dict = {}
    for item in list:
        key, value = next(iter(item.items()))
        dict[key] = value
    
    return dict