from math import sin, cos, sqrt, atan2, radians

# approximate radius of earth in km
R = 6373.0

#Caalculate distace between 2 points latitude and longitude by using haversine
def getDistance(lat1,lon1,lat2,lon2):

    lat1 = radians(lat1)
    lon1 = radians(lon1)
    lat2 = radians(lat2)
    lon2 = radians(lon2)

    #Delta longitude
    dlon = lon2 - lon1
    
    #Delta latitude
    dlat = lat2 - lat1

    a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    distance = R * c

    return distance