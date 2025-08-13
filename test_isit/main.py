# # testing/main.py

# from fastapi import FastAPI
# from pydantic import BaseModel
# import pandas as pd
# import os

# from functions import process_r5r  

# app = FastAPI()



# class InputRequest(BaseModel):
#     data_path: str
#     origin_str: str
#     destination_str: str
#     walk_time: int = 20
#     bicycle_time: int = 20
#     max_trip_duration: int = 120
#     car_time: int = 5
#     transit_freq_window_min: int = 60


# @app.get("/")
# async def read_root():
#     return {"message": "Welcome to the Trip Planner API"}


# @app.post("/process")
# def process_input(input_data: InputRequest):

#     csv_path = process_r5r(
#         data_path= r"C:\\Users\\z047364\\Desktop\\metz\\metz",
#         origin_str="49.06850402482493, 6.185948275507372",
#         destination_str="49.12038556570271, 6.176077061350479",
#         walk_time=20,
#         bicycle_time=20,
#         max_trip_duration=120,
#         car_time=5,
#         transit_freq_window_min=60
#     )

#     if not os.path.exists(csv_path):
#         return {"error": "CSV file not found"}

#     df = pd.read_csv(csv_path)
#     df = df.where(pd.notnull(df), None)
#     #result = df.to_dict(orient="records")

#     #os.remove(csv_path)
#     return df
#     #return {"trip_summary": result}






# # testing/main.py

# from fastapi import FastAPI, HTTPException
# from pydantic import BaseModel
# import pandas as pd
# import numpy as np
# import os
# import json

# from functions import process_r5r  

# app = FastAPI()


# class InputRequest(BaseModel):
#     data_path: str
#     origin_str: str
#     destination_str: str
#     walk_time: int = 20
#     bicycle_time: int = 20
#     max_trip_duration: int = 120
#     car_time: int = 5
#     transit_freq_window_min: int = 60

# @app.get("/")
# async def read_root():
#     return {"message": "Welcome to the Trip Planner API"}

# @app.post("/process")
# def process_input(input_data: InputRequest):

#     csv_path = process_r5r(
#         data_path=input_data.data_path,
#         origin_str=input_data.origin_str,
#         destination_str=input_data.destination_str,
#         walk_time=input_data.walk_time,
#         bicycle_time=input_data.bicycle_time,
#         max_trip_duration=input_data.max_trip_duration,
#         car_time=input_data.car_time,
#         transit_freq_window_min=input_data.transit_freq_window_min
#     )


#     if not os.path.exists(csv_path):
#         raise HTTPException(status_code=404, detail="CSV file not found.")

#     try:
#         df = pd.read_csv(csv_path)
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Failed to read CSV: {e}")


#     issues_log = []
#     issues_found = False

#     for col in df.columns:
#         nan_rows = df[df[col].isna()].index.tolist()
#         inf_rows = df[df[col] == float("inf")].index.tolist()
#         ninf_rows = df[df[col] == float("-inf")].index.tolist()

#         if nan_rows:
#             issues_log.append(f"Column '{col}' has NaN at rows: {nan_rows}")
#             issues_found = True
#         if inf_rows:
#             issues_log.append(f"Column '{col}' has +Infinity at rows: {inf_rows}")
#             issues_found = True
#         if ninf_rows:
#             issues_log.append(f"Column '{col}' has -Infinity at rows: {ninf_rows}")
#             issues_found = True

#     if issues_found:
#         issues_log.append("⚠ These values were replaced with null in JSON and CSV.")


#     df.replace([np.inf, -np.inf], np.nan, inplace=True)
#     df = df.astype(object).where(pd.notnull(df), None)


#     df.to_csv(csv_path, index=False)


#     cleaned_data = json.loads(df.to_json(orient="records"))
#     os.remove(csv_path)

#     return {
#         "trip_summary": cleaned_data,
#         "issues_detected": issues_found,
#         "log": issues_log,
#         "message": f"Cleaned data returned and saved to: {csv_path}"
#     }

















# testing/main.py

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import pandas as pd
import numpy as np
import os
import json
from collections import defaultdict

from functions import process_r5r  

app = FastAPI()


class InputRequest(BaseModel):
    data_path: str
    origin_str: str
    destination_str: str
    walk_time: int = 20
    bicycle_time: int = 20
    max_trip_duration: int = 120
    car_time: int = 5
    transit_freq_window_min: int = 60


def build_transport_structure(flat_data):
    """
    Takes flat list of trip records and rearranges them
    into the hierarchical Transport.json structure (values unchanged).
    """
    modes_dict = defaultdict(lambda: {"mode_type": None, "mode_lable": None, "routes": []})

    for row in flat_data:
        # Use Mode_Transport for grouping (values remain as-is)
        mode_type = row.get("Mode_Transport")
        mode_label = row.get("Mode_Transport")

        route_option = row.get("option")

        # Create new mode entry if needed
        if not modes_dict[mode_type]["mode_type"]:
            modes_dict[mode_type]["mode_type"] = mode_type
            modes_dict[mode_type]["mode_lable"] = mode_label

        # Find or create route entry
        route = next((r for r in modes_dict[mode_type]["routes"] if r["option"] == route_option), None)
        if not route:
            route = {"option": route_option, "segments": []}
            modes_dict[mode_type]["routes"].append(route)

        # Add segment (field names only changed, values unchanged)
        segment = {
            "mode": row.get("mode"),
            "order": row.get("segment"),  # renamed field
            "route_no": row.get("route"),
            "source": {
                "latitude": row.get("from_lat"),
                "longitude": row.get("from_lon")
            },
            "destination": {
                "latitude": row.get("to_lat"),
                "longitude": row.get("to_lon")
            },
            "geometry": row.get("geometry"),
            "duration": row.get("segment_duration"),
            "distance": row.get("distance"),
            "departure_time": row.get("departure_time"),
            "wait_time": row.get("wait")
        }
        route["segments"].append(segment)

    return {"transport_modes": list(modes_dict.values())}


@app.get("/")
async def read_root():
    return {"message": "Welcome to the Trip Planner API"}


@app.post("/process")
def process_input(input_data: InputRequest):

    csv_path = process_r5r(
        data_path=r"C:\\Users\\z047364\\Desktop\\metz\\metz",
        origin_str="49.06850402482493, 6.185948275507372",
        destination_str="49.12038556570271, 6.176077061350479",
        walk_time=20,
        bicycle_time=20,
        max_trip_duration=120,
        car_time=5,
        transit_freq_window_min=60
    )

    if not os.path.exists(csv_path):
        raise HTTPException(status_code=404, detail="CSV file not found.")

    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read CSV: {e}")

    issues_log = []
    issues_found = False

    for col in df.columns:
        nan_rows = df[df[col].isna()].index.tolist()
        inf_rows = df[df[col] == float("inf")].index.tolist()
        ninf_rows = df[df[col] == float("-inf")].index.tolist()

        if nan_rows:
            issues_log.append(f"Column '{col}' has NaN at rows: {nan_rows}")
            issues_found = True
        if inf_rows:
            issues_log.append(f"Column '{col}' has +Infinity at rows: {inf_rows}")
            issues_found = True
        if ninf_rows:
            issues_log.append(f"Column '{col}' has -Infinity at rows: {ninf_rows}")
            issues_found = True

    if issues_found:
        issues_log.append("⚠ These values were replaced with null in JSON and CSV.")

    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df = df.astype(object).where(pd.notnull(df), None)
    df.to_csv(csv_path, index=False)

    cleaned_data = json.loads(df.to_json(orient="records"))
    os.remove(csv_path)

    # Transform flat list into Transport.json hierarchy
    transformed_data = build_transport_structure(cleaned_data)

    return {
        "transport_data": transformed_data
    }














