from datetime import datetime,timedelta
import sys
import sqlite3
from Distance import getDistance

def CalculateTimDifference(time1,time2):
    
    t1 = time1.split(":")
    t2 = time2.split(":")
    
    a = datetime(2017, 5, 21, int(t1[0]), int(t1[1]), 00)
    
    if int(t2[0]) == 24:
        b = datetime(2017, 6, 21, 00, int(t2[1]), 00)
    else:
        b = datetime(2017, 5, 21, int(t2[0]), int(t2[1]), 00)

    c = b-a

    return c.total_seconds()

db = sys.argv[1]

conn = sqlite3.connect(db)

c = conn.cursor()

try:
    c.execute("alter table stopstime add distanceRelatedToPreviousStop float")
except Exception as err:
    print ("Column distanceRelatedToPreviousStop already in place")

try:
    c.execute("alter table stopstime add percentageTotalDistance float")
except Exception as err:
    print ("Column percentageTotalDistance already in place")

c.execute("select trip_id from trip")

rows = c.fetchall()

totalRows = len(rows)

i = 0

for row in rows:
    
    try:

        i += 1

        print("Record",i, "out of",totalRows)
        
        lat1 = 0
        lat2 = 0
        lon1 = 0
        lon2 = 0
        totalDistance = 0
        firstTime = ""
        lastTime = ""
        firstDate = None

        #Iterate trips to sum distance
        sqlStops = "select departure_time, stop_lat, stop_lon, s.stop_id from STOPSTIME s, STOPS s2 " \
                " where s.trip_id = '" + row[0] + "'" \
                " and   s.stop_id = s2.stop_id" \
                " order by stop_sequence"

        c1 = conn.cursor()
        c1.execute(sqlStops)
        rowsStops = c1.fetchall()

        for rowStops in rowsStops:
            
            if firstTime == "":
                firstTime = rowStops[0]
                t1 = firstTime.split(":")
                firstDate = datetime(2017, 5, 21, int(t1[0]), int(t1[1]), 00)
            
            lastTime = rowStops[0]

            if lat1 == 0:
                lat1 = rowStops[1]
                lon1 = rowStops[2]
            else:
                lat2 = rowStops[1]
                lon2 = rowStops[2]
                distance = getDistance(lat1,lon1,lat2,lon2)
                lat1 = lat2
                lon1 = lon2

                totalDistance += distance
                
                sqlUpdate = "update stopstime set distanceRelatedToPreviousStop = " + str(distance) + \
                            " where trip_id = '" + row[0] + "'" \
                            " and   stop_id = '" + rowStops[3] + "'"
                
                c3 = conn.cursor()
                c3.execute(sqlUpdate)

        totalDifference = CalculateTimDifference(firstTime, lastTime)

        #Iterate trips which do not contain time
        sqlStops = "select arrival_time, stop_lat, stop_lon, s.stop_id from STOPSTIME s, STOPS s2 " \
                " where s.trip_id = '" + row[0] + "'" \
                " and   s.stop_id = s2.stop_id" \
                " order by stop_sequence"

        c1 = conn.cursor()
        c1.execute(sqlStops)
        rowsStops = c1.fetchall()

        lat1 = 0
        lat2 = 0
        lon1 = 0
        lon2 = 0

        for rowStops in rowsStops:
            
            if lat1 == 0:
                lat1 = rowStops[1]
                lon1 = rowStops[2]
            else:
                lat2 = rowStops[1]
                lon2 = rowStops[2]
                distance = getDistance(lat1,lon1,lat2,lon2)
                lat1 = lat2
                lon1 = lon2

                percentageDistance = float(distance / totalDistance)
                secondsToAdd = totalDifference * percentageDistance

                firstDate = firstDate + timedelta(seconds=secondsToAdd)

                time = str(firstDate.time())[0:8]

                sqlUpdate = "update stopstime set arrival_time='" + time + "'" \
                            ",distanceRelatedToPreviousStop = " + str(distance) + \
                            " where trip_id = '" + row[0] + "'" \
                            " and   stop_id = '" + rowStops[3] + "'"
                
                c3 = conn.cursor()
                c3.execute(sqlUpdate)
    except Exception as err:
        print("Error in trip",row[0])
        print(err)

conn.commit()
conn.close()
