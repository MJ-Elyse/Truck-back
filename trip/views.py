from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.tokens import AccessToken
import requests
import math
from datetime import datetime, timezone
from django.utils.timezone import make_aware
import pytz

def get_route_data(waypoints):
    """
    Renvoie les donées de routes.
    """
    if len(waypoints) < 2:
        return None
    
    waypoints_str = ";".join([f"{lon},{lat}" for lat, lon in waypoints])
    osrm_url = f"http://router.project-osrm.org/route/v1/driving/{waypoints_str}?overview=false"
    
    response = requests.get(osrm_url)
    data = response.json()
    
    if "routes" in data and data["routes"]:
        return data["routes"][0]
    return None

def get_route_data_full(waypoints):
    """
    Renvoie les donées de routes full. 
    """
    if len(waypoints) < 2:
        return None

    waypoints_str = ";".join([f"{lon},{lat}" for lat, lon in waypoints])
    osrm_url = f"https://router.project-osrm.org/route/v1/driving/{waypoints_str}?overview=full&geometries=geojson"
    
    response = requests.get(osrm_url)
    data = response.json()

    if "routes" in data and data["routes"]:
        return data["routes"][0]
    
    return None

def get_route_distance(waypoints):
    routes = get_route_data(waypoints)
    if routes:
        return routes["distance"] / 1609.34
    return None

def get_route_duration(waypoints):
    routes = get_route_data(waypoints)
    if routes:
        return routes["duration"]
    return None

def get_apporx_coordinate_in_way_by_duration(waypoints, duration):
    data = get_route_data_full(waypoints)
    route = data["geometry"]["coordinates"]
    total_route_duration = data["duration"]

    if total_route_duration is None or total_route_duration == 0:
        return waypoints[0]
    
    if total_route_duration <= duration:
        return waypoints[-1]

    ind_min = 0
    ind_max = len(route) - 1
    ind_mid = math.ceil((ind_max + ind_min) / 2)

    while ind_max - ind_min > 1:
        around_duration = get_route_duration([[route[0][1], route[0][0]], [route[ind_mid][1], route[ind_mid][0]]])
        if around_duration is None:
            return waypoints[0]

        if compare_duration_with_tolerance(around_duration, duration):
            return (route[ind_mid][1], route[ind_mid][0])

        if around_duration < duration:
            ind_min = ind_mid
        else:
            ind_max = ind_mid

        ind_mid = math.ceil((ind_max + ind_min) / 2)
    return (route[ind_mid][1], route[ind_mid][0])

def get_apporx_coordinate_in_way(waypoints, distance):

    data = get_route_data_full(waypoints)

    route = data["geometry"]["coordinates"]
    total_route_distance = data["distance"] / 1609.34
    
    if total_route_distance is None or total_route_distance == 0:
        return waypoints[0]
    
    if total_route_distance <= distance:
        return waypoints[-1]
    
    ind_min = 0
    ind_max = len(route) - 1
    ind_mid = math.ceil((ind_max + ind_min) / 2)

    while ind_max - ind_min > 1:
        around_dist = get_route_distance([[route[0][1], route[0][0]], [route[ind_mid][1], route[ind_mid][0]]])
        if around_dist is None:
            return waypoints[0]

        if compare_with_tolerance(around_dist, distance):
            return (route[ind_mid][1], route[ind_mid][0])

        if around_dist < distance:
            ind_min = ind_mid
        else:
            ind_max = ind_mid

        ind_mid = math.ceil((ind_max + ind_min) / 2)

    return (route[ind_mid][1], route[ind_mid][0])

def compare_with_tolerance(dist1, dist2, tolerance = 10):
    threshold = (tolerance / 100) * dist1
    return abs(dist1 - dist2) <= threshold

def compare_duration_with_tolerance(duration1, duration2, tolerance = 10):
    threshold = (tolerance / 100) * duration1
    return abs(duration1 - duration2) <= threshold

def get_nearest_rest_area(lat, lng, radius=10000):
    query = f"""
        [out:json];
        (
        node["amenity"="fuel"](around:{radius},{lat},{lng});
        way["amenity"="fuel"](around:{radius},{lat},{lng});
        
        node["amenity"="parking"](around:{radius},{lat},{lng});
        way["amenity"="parking"](around:{radius},{lat},{lng});
        
        node["leisure"="picnic_site"](around:{radius},{lat},{lng});
        
        node["amenity"="fast_food"](around:{radius},{lat},{lng});
        node["amenity"="cafe"](around:{radius},{lat},{lng});
        );
        out body;
    """
    url = f"https://overpass-api.de/api/interpreter?data={requests.utils.quote(query)}"
    try:
        response = requests.get(url)
        data = response.json()

        rest_areas = [
            {
                "lat": el.get("lat"), 
                "lng": el.get("lon"), 
                "name": el.get("tags", {}).get("name", "Unnamed Rest Area"),
                "type": el.get("tags", {}).get("highway", "unknown")
            }
            for el in data.get("elements", [])
            if "lat" in el and "lon" in el
        ]

        return rest_areas

    except Exception as e:
        print(f"Error fetching rest areas: {e}")
        return []

def get_nearest_gas_station(lat, lng, radius=10000):
    query = f"""
        [out:json];
        (
        node["amenity"="fuel"](around:{radius},{lat},{lng});
        way["amenity"="fuel"](around:{radius},{lat},{lng});
        relation["amenity"="fuel"](around:{radius},{lat},{lng});
        );
        out body;
    """
    url = f"https://overpass-api.de/api/interpreter?data={requests.utils.quote(query)}"
    try:
        response = requests.get(url)
        data = response.json()
        stations = [
            {"lat": el.get("lat"), "lng": el.get("lon"), "name": el.get("tags", {}).get("name", "Unnamed Station")}
            for el in data.get("elements", [])
            if "lat" in el and "lon" in el
        ]
        return stations
    except Exception as e:
        print(f"Error fetching gas stations: {e}")
        return []
    
def get_points_refuelings(user_id, waypoints):
    try:
        distance_after_refueling = 0
        remaining_fuel_distance = (1000 - distance_after_refueling)
        coordinates = [[wp["lat"], wp["lng"]] for wp in waypoints]
        total_distance = get_route_distance(coordinates)

        if total_distance is None:
                return Response({"error": "Impossible de calculer l'itinéraire"}, status=status.HTTP_400_BAD_REQUEST)

        final_waypoints = [waypoints[0]]
        accumulated_distance = 0
        previous_point = waypoints[0]
        last_refuel_point = None
        
        for next_point in waypoints[1:]:
            coordinates = [[wp["lat"], wp["lng"]] for wp in [previous_point, next_point]]
            segment_distance = get_route_distance(coordinates)
            
            if segment_distance is None :
                continue

            accumulated_distance += segment_distance

            while (accumulated_distance > remaining_fuel_distance):
                coordinates = [[wp["lat"], wp["lng"]] for wp in [previous_point, next_point]]
                approx_point = get_apporx_coordinate_in_way(coordinates, remaining_fuel_distance - (accumulated_distance - segment_distance))
                gas_stations = get_nearest_gas_station(approx_point[0], approx_point[1])
                if not gas_stations:
                    return Response({"error": "Aucune station trouvée pour le refueling"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)  

                closest_station = gas_stations[0]
                final_waypoints.append({
                    "lat": closest_station["lat"],
                    "lng": closest_station["lng"],
                    "label": f"refueling - {closest_station['name']}",
                    "duration": {15 * 60},
                    "type": "on-duty"
                })

                last_refuel_point = (closest_station["lat"], closest_station["lng"])
                accumulated_distance = get_route_distance([last_refuel_point, [next_point['lat'], next_point['lng']]])
                remaining_fuel_distance = 1000
                previous_point = [closest_station["lat"], closest_station["lng"]]

            final_waypoints.append(next_point)
            previous_point = next_point
        last_refuel_to_dropoff_distance = get_route_distance([last_refuel_point, [waypoints[-1]['lat'], waypoints[-1]['lng']]]) if last_refuel_point else None
        return {
            "waypoints": final_waypoints,
            "total_distance": total_distance,
            "last_refuel_to_dropoff_distance": last_refuel_to_dropoff_distance
        }
    
    except Exception as e:
        raise e
   
class TripConfigAddPoint(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        
        access_token = request.headers.get('Authorization')

        if access_token and access_token.startswith('Bearer '):
            access_token = access_token.split(' ')[1]
        else:
            return Response({'detail': 'Invalid token format'}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            access = AccessToken(access_token)
            user_id = access['user_id']
            current = (float(request.GET.get("current_lat")), float(request.GET.get("current_lng")))
            pickup = (float(request.GET.get("pickup_lat")), float(request.GET.get("pickup_lng")))
            dropoff = (float(request.GET.get("dropoff_lat")), float(request.GET.get("dropoff_lng")))
            remaining_time_driving, rest_duration = 11 * 3600, 8 * 3600   

            waypoints = [current, pickup, dropoff] 
            total_duration = get_route_duration(waypoints)
            if total_duration is None:
                return Response({"error": "Unable to calculate route"}, status=status.HTTP_400_BAD_REQUEST)

            final_waypoints = [{
                "lat": current[0],
                "lng": current[1], 
                "label": "current",
                "duration": {0},
                "type": "on-duty/driving"
            }]

            accumulated_duration = 0
            previous_point = current
            last_rest_area_point = None
            for next_point in [pickup, dropoff]:
                segment_duration = get_route_duration([previous_point, next_point])
                if segment_duration is None :
                    continue

                accumulated_duration += segment_duration

                if(rest_duration is not None and accumulated_duration > rest_duration):
                    approx_point = get_apporx_coordinate_in_way_by_duration([previous_point, next_point], (rest_duration - (accumulated_duration - segment_duration)))
                    rest_area = get_nearest_rest_area(approx_point[0], approx_point[1])
                    if not rest_area:
                        return Response({"error": "Aucune aire trouvée"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)  
                    closest_rest_area = rest_area[0]
                    final_waypoints.append({
                        "lat": closest_rest_area["lat"],
                        "lng": closest_rest_area["lng"],
                        "label": f"Rest Area - {closest_rest_area['name']}",
                        "duration": {30 * 60},
                        "type": "off-duty/on-duty"
                    })
                    last_rest_area_point = [closest_rest_area['lat'], closest_rest_area['lng']]
                    rest_duration = None

                while(accumulated_duration > remaining_time_driving):
                    if(rest_duration is not None and accumulated_duration > rest_duration):
                        approx_point = get_apporx_coordinate_in_way_by_duration([previous_point, next_point], (rest_duration - (accumulated_duration - segment_duration)))
                        rest_area = get_nearest_rest_area(approx_point[0], approx_point[1])

                        if not rest_area:
                            return Response({"error": "Aucune aire trouvée pour le refueling"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)  

                        closest_rest_area = rest_area[0]
                        final_waypoints.append({
                            "lat": closest_rest_area["lat"],
                            "lng": closest_rest_area["lng"],
                            "label": f"Rest Area - {closest_rest_area['name']}",
                            "duration": {30 * 60},
                            "type": "off-duty/on-duty"
                        })
                        last_rest_area_point = [closest_rest_area['lat'], closest_rest_area['lng']]
                        rest_duration = None

                    approx_point = get_apporx_coordinate_in_way_by_duration([previous_point, next_point], (remaining_time_driving - (accumulated_duration - segment_duration)))
                    rest_area = get_nearest_rest_area(approx_point[0], approx_point[1])

                    if not rest_area:
                        return Response({"error": "Aucune aire trouvée pour le refueling"}, status=status.HTTP_400_BAD_REQUEST)  

                    closest_rest_area = rest_area[0]
                    last_rest_area_point = [closest_rest_area['lat'], closest_rest_area['lng']]
                    final_waypoints.append({
                        "lat": closest_rest_area["lat"],
                        "lng": closest_rest_area["lng"],
                        "label": f"Area - {closest_rest_area['name']}",
                        "duration": {10 * 3600},
                        "type": "sleeper"
                    })
                    previous_point = last_rest_area_point
                    remaining_time_driving = 11 * 3600
                    rest_duration = 8 * 3600
                    accumulated_duration = get_route_duration([previous_point, next_point])

                final_waypoints.append({
                    "lat": next_point[0], 
                    "lng": next_point[1], 
                    "label": "pickup" if next_point == pickup else "dropoff",
                    "duration": {1 * 3600},
                    "type": "on-duty"
                })
                previous_point = next_point

            result = get_points_refuelings(user_id, final_waypoints)
            waypoints_results = result["waypoints"]
            
            prev_point = waypoints_results[0]
            prev_point["duration_from_last_point"] = 0
            waypoints_results_final = [prev_point]
            
            for wp in waypoints_results[1:]:
                wp["duration_from_last_point"] = get_route_duration([[prev_point['lat'], prev_point['lng']], [wp['lat'], wp['lng']]])
                waypoints_results_final.append(wp)
                prev_point = wp

            distance = result["total_distance"]
            distance_to_dropoff = result["last_refuel_to_dropoff_distance"]
            
            response_data = {
                "waypoints": waypoints_results_final,
                "total_distance": distance,
            }

            if distance_to_dropoff is not None:
                response_data["distance_to_dropoff"] = distance_to_dropoff

            return Response(response_data, status=status.HTTP_200_OK)
        
        except Exception as e:
            return Response({'detail': f'Error: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR) 