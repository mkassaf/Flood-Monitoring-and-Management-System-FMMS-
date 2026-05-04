#!/usr/bin/env python3
"""Seed initial FMMS data via geo-service and auth-service REST APIs."""
import argparse
import hashlib
import json
import secrets
import sys
from pathlib import Path

import httpx

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--geo-url", default="http://localhost:8005")
    parser.add_argument("--auth-url", default="http://localhost:8006")
    args = parser.parse_args()

    geo = args.geo_url.rstrip("/")
    auth = args.auth_url.rstrip("/")

    sensor_tokens: dict[str, str] = {}

    # Create regions
    regions = {}
    for name in ["North", "Center", "South"]:
        r = httpx.post(f"{geo}/regions", json={"name": name})
        r.raise_for_status()
        region = r.json()
        regions[name] = region["region_id"]
        print(f"Region {name}: {region['region_id']}")

    # Create cities (2 per region)
    cities = {}
    city_names = {
        "North": ["Milan", "Turin"],
        "Center": ["Rome", "Florence"],
        "South": ["Naples", "Palermo"],
    }
    for region_name, rnames in city_names.items():
        for cname in rnames:
            r = httpx.post(f"{geo}/cities", json={"region_id": regions[region_name], "name": cname})
            r.raise_for_status()
            city = r.json()
            cities[cname] = city["city_id"]
            print(f"City {cname}: {city['city_id']}")

    # Create areas (3 per city) and sensors (3 per area)
    area_ids_by_city: dict[str, list[str]] = {}
    all_area_ids: list[str] = []

    for city_name, city_id in cities.items():
        area_ids_by_city[city_name] = []
        for i in range(1, 4):
            area_name = f"{city_name} District {i}"
            r = httpx.post(f"{geo}/areas", json={"city_id": city_id, "name": area_name, "risk_profile": "standard"})
            r.raise_for_status()
            area = r.json()
            area_id = area["area_id"]
            area_ids_by_city[city_name].append(area_id)
            all_area_ids.append(area_id)
            print(f"Area {area_name}: {area_id}")

            # Set thresholds
            for param, warning, critical in [
                ("water_level_m", 2.0, 3.0),
                ("rainfall_mm_h", 20.0, 30.0),
                ("soil_saturation_pct", 70.0, 90.0),
            ]:
                httpx.put(
                    f"{geo}/areas/{area_id}/thresholds/{param}",
                    json={"warning_hi": warning, "critical_hi": critical},
                ).raise_for_status()

            # Create sensors
            for j in range(1, 4):
                r = httpx.post(f"{geo}/sensors", json={"area_id": area_id, "label": f"Sensor {j}"})
                r.raise_for_status()
                sensor = r.json()
                sensor_tokens[sensor["sensor_id"]] = sensor["token"]

    # Save tokens
    Path("secrets").mkdir(exist_ok=True)
    Path("secrets/sensor_tokens.json").write_text(json.dumps(sensor_tokens, indent=2))
    print(f"Saved {len(sensor_tokens)} sensor tokens to secrets/sensor_tokens.json")

    # Create demo users
    area_user_areas = all_area_ids[:4]
    city_user_cities = list(cities.values())[:2]
    region_user_regions = list(regions.values())[:1]

    users = [
        {"email": "area_manager@fmms.local", "password": "Test1234!", "role": "area_manager", "jurisdiction": area_user_areas},
        {"email": "city_manager@fmms.local", "password": "Test1234!", "role": "city_manager", "jurisdiction": city_user_cities},
        {"email": "regional_manager@fmms.local", "password": "Test1234!", "role": "regional_manager", "jurisdiction": region_user_regions},
    ]
    for u in users:
        r = httpx.post(f"{auth}/users", json=u)
        if r.status_code == 409:
            print(f"User {u['email']} already exists")
        else:
            r.raise_for_status()
            print(f"Created user {u['email']}")

    print("\nSeed complete!")

if __name__ == "__main__":
    main()
