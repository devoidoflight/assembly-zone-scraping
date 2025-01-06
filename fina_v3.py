import http.client
import json
import urllib.parse
import re
import pandas as pd
from shapely.geometry import Point, Polygon, MultiPolygon
import matplotlib.pyplot as plt
import numpy as np


# Function to parse the curl bash command into usable components
def clean_curl_request(curl_command):
    # Extract the URL
    url_pattern = r"curl '(.*?)'"
    match = re.search(url_pattern, curl_command)
    if match:
        url = match.group(1)
    else:
        raise ValueError("URL not found in the curl command")

    # Extract headers
    headers = {}
    header_pattern = r"-H '([^:]+): (.*?)'"
    for header_match in re.finditer(header_pattern, curl_command):
        header_name = header_match.group(1)
        header_value = header_match.group(2)
        headers[header_name] = header_value

    # Extract data
    data_pattern = r"--data-raw '(.*?)'"
    match = re.search(data_pattern, curl_command)
    data = {}
    if match:
        data_string = match.group(1)
        data_items = data_string.split("&")
        for item in data_items:
            key, value = item.split("=")
            data[key] = urllib.parse.unquote(value)

    # Parse URL for host and path
    parsed_url = urllib.parse.urlparse(url)
    host = parsed_url.netloc
    path = parsed_url.path + ("?" + parsed_url.query if parsed_url.query else "")

    return host, path, data, headers



# Function to send requests dynamically
def send_request(host, path, data, headers, lat, lng):
    # Update latitude and longitude in the data dictionary
    data["lat"] = str(lat)
    data["lng"] = str(lng)

    # Set up the connection
    connection = http.client.HTTPSConnection(host)

    # Send the POST request
    connection.request("POST", path, body=urllib.parse.urlencode(data), headers=headers)

    # Get the response
    response = connection.getresponse()
    response_data = response.read().decode()

    # Close the connection
    connection.close()

    # Check for a successful response and return the result
    if response.status == 200:
        return json.loads(response_data)
    else:
        return f"Error: {response.status}, {response_data}"
    


def load_geojson(filepath, ilce):
    with open(filepath, 'r', encoding='utf-8') as file:
        data = json.load(file)
    return [feature for feature in data["features"] if feature["properties"].get("name") == ilce]

def extract_polygons(features):
    polygons = []
    for feature in features:
        geometry_type = feature["geometry"].get("type")
        coordinates = feature["geometry"].get("coordinates")
        if geometry_type == "Polygon":
            polygons.extend([Polygon(coordinates[0])])
        elif geometry_type == "MultiPolygon":
            polygons.extend([Polygon(polygon[0]) for polygon in coordinates])
        else:
            raise ValueError(f"Unsupported geometry type: {geometry_type}")
    return polygons

def generate_grid(polygons, aralik):
    red_points = []
    lat_spacing = aralik / 111320
    for polygon in polygons:
        min_lat = min(polygon.exterior.coords.xy[1])
        max_lat = max(polygon.exterior.coords.xy[1])
        lat_lines = np.arange(min_lat, max_lat, lat_spacing)
        for lat in lat_lines:
            min_lon = min(polygon.exterior.coords.xy[0])
            max_lon = max(polygon.exterior.coords.xy[0])
            lon_spacing = aralik / (111320 * np.cos(np.radians(lat)))
            lon_points = np.arange(min_lon, max_lon, lon_spacing)
            for lon in lon_points:
                point = Point(lon, lat)
                if any(polygon.contains(point) for polygon in polygons):
                    red_points.append((lon, lat))
    return red_points,polygons

def process_api_requests(red_points, send_request_func, polygons):
    columns = ["tesis_adi", "il_adi", "sokak_adi", "ilce_adi", "mahalle_adi", "lng", "lat", "id", "polygon_bounds"]
    df = pd.DataFrame(columns=columns)
    for lng, lat in red_points:
        result = send_request_func(lat, lng)
        if isinstance(result, dict) and "features" in result:
            for feature in result["features"]:
                properties = feature["properties"]
                row = {
                    "tesis_adi": properties.get("tesis_adi", ""),
                    "il_adi": properties.get("il_adi", ""),
                    "sokak_adi": properties.get("sokak_adi", ""),
                    "ilce_adi": properties.get("ilce_adi", ""),
                    "mahalle_adi": properties.get("mahalle_adi", ""),
                    "lng": lng,
                    "lat": lat,
                    "id": properties.get("id", ""),
                    "polygon_bounds": polygons  # Now passed explicitly
                }
                df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    return df.drop_duplicates(subset=["id"])

def process_district(ilce, aralik, geojson_filepath, curl_command):
    # Parse the curl command
    host, path, data, headers = clean_curl_request(curl_command)
    
    # Load GeoJSON and process data
    features = load_geojson(geojson_filepath, ilce)
    polygons = extract_polygons(features)
    red_points, polygons = generate_grid(polygons, aralik)  # Unpack both

    # Define the function for API requests
    send_request_func = lambda lat, lng: send_request(host, path, data, headers, lat, lng)
    
    # Debugging: Ensure send_request_func is correct
    print(type(send_request_func))  # Should print <class 'function'>
    
    # Process API requests
    df = process_api_requests(red_points, send_request_func, polygons)  # Pass polygons explicitly
    print(df.head(10))
    
    # Save results
    save_dataframe(df, f"./results/{ilce}_results.csv")


# Example usage
curl_command = """
curl 'https://www.turkiye.gov.tr/afet-ve-acil-durum-yonetimi-acil-toplanma-alani-sorgulama?harita=goster&submit' \
  -H 'Accept: application/json, text/javascript, */*; q=0.01' \
  -H 'Accept-Language: tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7' \
  -H 'Connection: keep-alive' \
  -H 'Content-Type: application/x-www-form-urlencoded; charset=UTF-8' \
  -H 'Cookie: ridbb=WyI1ZWZjYWJjN2E5YzNiY2M4ZDY4OWExMGIwN2IwMTcyMmNjZDc5NjUzZDBlOCJd; _uid=1721632846-0ba03683-f088-45be-ab36-f8dd67f8b32d; w3p=1943251136.20480.0000; language=tr_TR.UTF-8; TURKIYESESSIONID=l4c0eutds26b2qr2ghqjf9mbt4; TS015d3f68=015c1cbb6d4e928d45ebedcaf5f342463b1af2784efbf500c1f6decb2c89203531d7857aa9a09cfd104886882fa33f5d9939ca8b25; _lastptts=1736076251' \
  -H 'Origin: https://www.turkiye.gov.tr' \
  -H 'Referer: https://www.turkiye.gov.tr/afet-ve-acil-durum-yonetimi-acil-toplanma-alani-sorgulama?harita=goster' \
  -H 'Sec-Fetch-Dest: empty' \
  -H 'Sec-Fetch-Mode: cors' \
  -H 'Sec-Fetch-Site: same-origin' \
  -H 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 OPR/115.0.0.0' \
  -H 'X-Requested-With: XMLHttpRequest' \
  -H 'sec-ch-ua: "Chromium";v="130", "Opera";v="115", "Not?A_Brand";v="99"' \
  -H 'sec-ch-ua-mobile: ?0' \
  -H 'sec-ch-ua-platform: "Windows"' \
  --data-raw 'pn=%2Fafet-ve-acil-durum-yonetimi-acil-toplanma-alani-sorgulama&ajax=1&token=%7B0D0EDF-DF6CA3-CCC1F6-D2625A-041FAE-37ADE8-78EE4A-7ABBD4%7D&islem=getAlanlarForNokta&lat=40.97019355753538&lng=29.096558208723692'
"""
# Replace `send_request` with your actual API call function.
process_district("Adalar", 100, "istanbul-admin-level-6.geojson", curl_command)