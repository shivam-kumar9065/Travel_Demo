import streamlit as st
import pandas as pd
import pydeck as pdk
import time
import base64
from shapely.wkt import loads
import streamlit.components.v1 as components
from datetime import datetime, timedelta
import qrcode
from io import BytesIO
from PIL import Image

# === Session State ===
if 'search_triggered' not in st.session_state:
    st.session_state['search_triggered'] = False
if 'clicked_icon_index' not in st.session_state:
    st.session_state['clicked_icon_index'] = None

# === Read Clicked Icon from URL ===
query_params = st.query_params
if 'clicked' in query_params:
    try:
        clicked_index = int(query_params['clicked'])
        st.session_state['clicked_icon_index'] = clicked_index
        st.query_params.clear()
    except ValueError:
        st.session_state['clicked_icon_index'] = None

# === Page Config ===
st.set_page_config(page_title="Travel Companion", layout="centered")

# === CSS Styling ===
st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Dancing+Script&display=swap');
        @import url('https://fonts.googleapis.com/css2?family=Browallia+New');
        * { font-family: 'Browallia New', sans-serif; }
        .stApp { background-color: #C1E5F5; }
        section[data-testid="stSidebar"] {
            background-color: white;
            padding: 2rem 1rem;
        }
        .sidebar-title {
            font-family: 'Dancing Script', cursive;
            font-size: 50px;
            margin: -10px 0 0 10px;
        }
        .section-heading {
            font-size: 28px;
            font-weight: bold;
            margin: 30px 0 20px;
        }
            .normal-font {
            font-size: 24px;
            margin: 30px 0 20px;
        }
        div[data-testid="stTextInput"] input,
        div[data-testid="stNumberInput"] input {
            background-color: #CBE8F6;
            border: none;
            border-radius: 8px;
            padding: 0.5em 1em;
            font-size: 24px;
        }
        div.stButton > button {
            background-color: #A6CAEC;
            border: none;
            border-radius: 10px;
            padding: 0.3em 1em;
            font-size: 24px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;

            
        }
    </style>
""", unsafe_allow_html=True)

# === Sidebar ===
with st.sidebar:
    col1, col2 = st.columns([1, 4])
    with col1:
        st.image("static/renault.jpg", width=100)
    with col2:
        st.markdown('<div class="sidebar-title">Travel companion</div>', unsafe_allow_html=True)

    st.markdown('<div class="section-heading">User settings</div>', unsafe_allow_html=True)
    st.markdown('<div class="normal-font">Set your vehicle\'s availability</div>', unsafe_allow_html=True)

    car = st.checkbox("Car", key="car_mode")
    bicycle = st.checkbox("Bicycle", key="bicycle_mode")
    walk = st.checkbox("Walk", key="walk_mode")

  

    if bicycle:
        st.markdown("<p style='font-size:20px;'>Bicycle Peddle (in mins)</p>", unsafe_allow_html=True)
        bicycle_mins = st.number_input("", min_value=0, step=1, format="%d", key="bicycle_input")

    if walk:
        st.markdown("<p style='font-size:20px; '>Walk (mins)</p>", unsafe_allow_html=True)
        walk_mins = st.number_input("", min_value=0, step=1, format="%d", key="walk_input")

    st.markdown("<p style='font-size:20px;'>Other specification (optional)</p>", unsafe_allow_html=True)
    other_options = st.text_input(label="")

    col1, col2 = st.columns([1, 1])
    def reset_fields():
        for key in ["car_mode", "bicycle_mode", "walk_mode", "bicycle_minutes", "walk_minutes", "other_options"]:
            if key in st.session_state:
                del st.session_state[key]

    with col1:
        st.button("Reset", on_click=reset_fields)
    with col2:
        submit_clicked = st.button("Submit")

    if submit_clicked:
        success_placeholder = st.empty()
        success_placeholder.success("You have successfully submitted your preference")
        time.sleep(1)
        success_placeholder.empty()

# === Main Area: Search bar ===
col1, col2 = st.columns([1, 6])
with col1:
    st.image("static/pin.jpg", width=50)
with col2:
    current_location = st.text_input("", placeholder="Current location", label_visibility="collapsed")
    destination = st.text_input("", placeholder="Metz cathedral", label_visibility="collapsed", key="destination_input")
    if st.button('🔍 Search'):
        st.session_state['search_triggered'] = True
        st.session_state['clicked_icon_index'] = None
def embed_image(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

# === Read options and transport images ===
option_df = pd.read_csv("fin_2_concat.csv")
img_dir = "static/"
optimal_mode = "bicycle+transit"  # <- this should come from your backend logic

# === Image Config ===
base_modes = [
    {"mode": "car", "label": "Car", "default_img": "car.jpg", "alt_img": "car1.jpg"},
    {"mode": "bicycle", "label": "Bicycle", "default_img": "bicycle.jpg", "alt_img": "bicycle1.jpg"},
    {"mode": "car+transit", "label": "Car + Transit", "default_img": "car_transit.jpg", "alt_img": "car_transit1.jpg"},
    {"mode": "bicycle+transit", "label": "Bicycle + Transit", "default_img": "bicycle_transit.jpg", "alt_img": "bicycle_transit_1.jpg"},
    {"mode": "walk+transit", "label": "Walk + Transit", "default_img": "walk_transit.jpg", "alt_img": "walk_transit1.jpg"},
]

images = []
for item in base_modes:
    image_filename = item["alt_img"] if item["mode"] == optimal_mode else item["default_img"]
    images.append({
        "filename": image_filename,
        "mode": item["mode"],
        "label": item["label"]
    })

# === Render Mode Icons ===
if st.session_state.get('search_triggered') or st.session_state.get('clicked_icon_index') is not None:
    cols = st.columns(5)
    for i, col in enumerate(cols):
        with col:
            path = f"{img_dir}{images[i]['filename']}"
            b64img = embed_image(path)
            target = f"?clicked={i}"
            col.markdown(f"""
                <div style="text-align:center;">
                    <a href="{target}" target="_self" style="text-decoration:none; color: inherit;">
                        <div style="display: flex; flex-direction: column; align-items: center;">
                            <img src="data:image/jpeg;base64,{b64img}" width="80" style="border-radius:50%; margin-bottom:6px; cursor:pointer;" />
                            <div style="font-size:14px; background-color:#CBE8F6; padding:6px 10px; border-radius:8px; color: {'red' if st.session_state.get('clicked_icon_index') == i else 'black'};">
    {images[i]["label"]}
</div>
                        </div>
                    </a>
                </div>
            """, unsafe_allow_html=True)



# === Map + Journey Breakdown ===
clicked = st.session_state['clicked_icon_index']
if clicked is not None:
    selected_transport = images[clicked]["mode"]
    from_lat, from_lon = 49.10667, 6.234854
    to_lat, to_lon = 49.09702, 6.139394
    tolerance = 0.005

    mode_filtered_df = option_df[option_df["Mode_Transport"].str.lower() == selected_transport.lower()]
    grouped = mode_filtered_df.groupby("option")
    matching_options = [
        opt for opt, group in grouped
        if abs(group["from_lat"].iloc[0] - from_lat) <= tolerance and
           abs(group["from_lon"].iloc[0] - from_lon) <= tolerance and
           abs(group["to_lat"].iloc[-1] - to_lat) <= tolerance and
           abs(group["to_lon"].iloc[-1] - to_lon) <= tolerance
    ]

    filtered_df = mode_filtered_df[mode_filtered_df["option"].isin(matching_options)]
    if filtered_df.empty:
        st.warning("No route data available for selected mode.")
    else:
        selected_opt = sorted(filtered_df['option'].unique())[0]
        opt_df = filtered_df[filtered_df["option"] == selected_opt]

        color_map = {
            "walk": [51, 136, 255],
            "car": [255, 87, 51],
            "bicycle": [51, 204, 51],
            "bus": [128, 0, 128],
            "transit": [128, 0, 128]
        }

        route_lines = []
        for _, row in opt_df.iterrows():
            if pd.notna(row['geometry']):
                line = loads(row['geometry'])
                coords = [[lon, lat] for lon, lat in line.coords]
                base_mode = row["mode"].split('+')[0].lower()
                route_lines.append({
                    'coordinates': coords,
                    'mode': base_mode,
                    'color': color_map.get(base_mode, [0, 0, 0]),
                    'tooltip': base_mode.capitalize()
                })

        if not route_lines:
            st.warning("No route data available for selected mode.")
        else:
            first_coords = route_lines[0]['coordinates'][0]
            view_state = pdk.ViewState(
                latitude=first_coords[1],
                longitude=first_coords[0],
                zoom=12,
                pitch=45
            )

            path_layer = pdk.Layer(
                type="PathLayer",
                data=route_lines,
                get_path="coordinates",
                get_color="color",
                width_scale=10,
                width_min_pixels=2,
                pickable=True,
                auto_highlight=True,
                get_width=4
            )

            marker_data = pd.DataFrame([
                {"lat": from_lat, "lon": from_lon, "label": "Start","color": [255, 102, 0],"tooltip": "Origin"},
                {"lat": to_lat, "lon": to_lon, "label": "Destination","color": [0, 200, 0],"tooltip": "Destination"}
            ])
            marker_layer = pdk.Layer(
                "ScatterplotLayer",
                data=marker_data,
                get_position='[lon, lat]',
                get_color='[200, 30, 0, 160]',
                get_radius=50
            )
            opt_df = filtered_df[filtered_df["option"] == selected_opt]
            # === Extract Optimal Parking Zones for car & bicycle
            parking_zones = opt_df[opt_df["mode"].str.lower().isin(["car", "bicycle"])][["to_lat", "to_lon"]].drop_duplicates()

            parking_df = pd.DataFrame({
            "lat": parking_zones["to_lat"],
            "lon": parking_zones["to_lon"],
            "tooltip": "Optimal Parking Zone"})
            parking_layer = pdk.Layer(
            "ScatterplotLayer",
            data=parking_df,
            get_position='[lon, lat]',
            get_color='[0, 0, 255, 160]',  # Blue dots
            get_radius=60,
            pickable=True)

            st.pydeck_chart(pdk.Deck(
        map_style="mapbox://styles/mapbox/light-v9",
        initial_view_state=view_state,
        layers=[path_layer, marker_layer, parking_layer],  # ✅ added parking_layer
        tooltip={"text": "{tooltip}"}
),use_container_width=True,  # ✅ 100% width of parent container
    height=600)
            
            # Get current time
            start_time = datetime.now()

            # Total trip duration in minutes
            total_duration = int(opt_df['segment_duration'].sum())

            # Calculate end time
            end_time = start_time + timedelta(minutes=total_duration)

            # Format both for display
            start_time_str = start_time.strftime("%I:%M %p")
            end_time_str = end_time.strftime("%I:%M %p")
            # === Breakdown
            total_distance = int(opt_df["distance"].sum())
            total_duration = int(opt_df["segment_duration"].sum())
            co2_emission = float(opt_df['co2_emission(kg) '].sum()) 
            
            breakdown = f"""
                <p style="color:#2196F3;font-weight:bold">
                    <b>Trip details:</b> 📏 {opt_df['distance'].sum():.2f} kms – 🕒 {total_duration} mins 
                     – 
                    🌱 {opt_df['co2_emission(kg) '].sum():.4f} kg co2

                </p>
                <p style="font-weight:bold;margin-top:10px;">⏰ {start_time_str} ➡️ {end_time_str}</p>
                <p style="font-weight:bold;margin-top:10px;">Journey breakdown</p>
            """

            breakdown += """
                <style>
                    .segment-line {
                        border-left: 2px dashed #aaa;
                        margin-left: 9px;
                        padding-left: 12px;
                        position: relative;
                    }
                    .dot {
                        width: 10px;
                        height: 10px;
                        background-color: #fff;
                        border: 2px solid #000;
                        border-radius: 50%;
                        position: absolute;
                        left: -6px;
                        top: 6px;
                    }
                    .segment-row {
                        margin-bottom: 14px;
                        line-height: 1.4em;
                    }
                </style>
            """

            for _, row in opt_df.iterrows():
                mode = row["mode"].capitalize()
                segment_dist = float(row["distance"])
                time = int(row["segment_duration"])
                route = row["route"]
                icon = {
                "Walk": "🚶‍♂️",
                "Bus": "🚌",
                "Bicycle": "🚴‍♀️",
                "Car": "🚗",
                "Transit": "🚌"
                    }.get(mode, "➤")

                route_str = f" (route {route})" if pd.notna(route) and str(route).strip() else ""
                desc = f"{icon} {mode}{route_str} ({segment_dist:.2f} kms) – {time} mins"

    # Add extra details
                extra_lines = ""
                if mode == "Bus":
                    ticket_price = row.get("ticket_price(euro)", 0)
                    wait_time = row.get("wait", 0)
                    route_id = row.get("route", "N/A")
                    frequency=row.get("frequency(buses per hour)",0)
                    last_bus_time=row.get("last_bus_time","N/A")
                    st.markdown(f"### 🚌 Get Bus Ticket for Route {route_id}")
                    st.markdown(f"""
                    🎟️ Ticket Price: €{ticket_price} per person <br>
                    🕒 Wait time: {wait_time} mins <br>
                    🔚 Last bus: {last_bus_time} <br>
                    🔁 Frequency: {int(frequency)} buses/h""", unsafe_allow_html=True)

                # Initialize session state variables
                    if f"step_{route_id}" not in st.session_state:
                        st.session_state[f"step_{route_id}"] = "start"

                    step = st.session_state[f"step_{route_id}"]

    # Step 1: Show Book Ticket button
                    if step == "start":
                        if st.button("Book Ticket"):
                            st.session_state[f"step_{route_id}"] = "ask_passengers"
                            st.rerun()

    # Step 2: Ask for number of passengers
                    elif step == "ask_passengers":
                        num_passengers = st.number_input("Enter number of passengers", min_value=1, step=1, key=f"passengers_{route_id}")
                        if st.button("Generate QR Code"):
                                st.session_state[f"num_passengers_{route_id}"] = num_passengers
                                st.session_state[f"step_{route_id}"] = "show_qr"
                                st.rerun()

    # Step 3: Generate and show QR code
                    elif step == "show_qr":
                        num_passengers = st.session_state.get(f"num_passengers_{route_id}", 1)
                        qr_text = f"Route: {route_id} | Passengers: {num_passengers} | Price per Ticket: €{ticket_price} | Total: €{ticket_price * num_passengers}"

                        # Create QR code with smaller size
                        qr = qrcode.QRCode(
                        version=1,
                        error_correction=qrcode.constants.ERROR_CORRECT_L,
                        box_size=4,  # smaller value = smaller QR code
                        border=2     # optional: reduce border size too
                        )
                        qr.add_data(qr_text)
                        qr.make(fit=True)

                        img = qr.make_image(fill_color="black", back_color="white")

                        buf = BytesIO()
                        img.save(buf)
                        buf.seek(0)
                        st.image(Image.open(buf), caption="🎫 Your Ticket QR Code")
                        st.success("Ticket booked successfully!")

                        if st.button("Book Another Ticket"):
                            st.session_state[f"step_{route_id}"] = "start"
                            st.rerun()
                    
                elif mode in ["Car"]:
                    parking = float(row.get("parking_cost(euro per hour)", 0))
                    extra_lines += f"""<div class="segment-extra">🅿️ Parking € {parking}/hr</div>"""
                

                breakdown += f"""
    <div class="segment-row">
        <div class="dot"></div>
        <div class="segment-line">
            <div>{desc}</div>
            {extra_lines}
        </div>
    </div>
    """


            # Swipe-Up Panel
            components.html(f"""
                <div class="sheet-container" id="sheet">
                    <div class="handle" onclick="toggleSheet()">▼</div>
                    <div class="sheet-content">
                        {breakdown}
                    </div>
                </div>
                <style>
                  .sheet-container {{
                    width: 100%;
                    margin-top: 20px;
                    background-color: #fff;
                    border-radius: 16px;
                    box-shadow: 0 0 10px rgba(0,0,0,0.1);
                    overflow: hidden;
                    transition: max-height 0.4s ease;
                    max-height: 160px;
                  }}
                  .sheet-container.expanded {{
                    max-height: 600px;
                  }}
                  .handle {{
                    width: 60px;
                    height: 6px;
                    background: #ccc;
                    border-radius: 3px;
                    margin: 10px auto;
                    cursor: pointer;
                    text-align: center;
                    font-size: 18px;
                    font-weight: bold;
                  }}
                  .sheet-content {{
                    padding: 10px 20px;
                    font-family: sans-serif;
                    font-size: 16px;
                    overflow-y: auto;
                    max-height: 520px;
                  }}
                </style>
                <script>
                  function toggleSheet() {{
                    let sheet = document.getElementById("sheet");
                    let handle = document.querySelector(".handle");
                    sheet.classList.toggle("expanded");
                    handle.innerHTML = sheet.classList.contains("expanded") ? "▲" : "▼";
                  }}
                </script>
            """, height=650)

# === Map Legend ===
            st.markdown("""
<div style='
    position: absolute;
    bottom: 1000px;
    right: 30px;
    width: 3cm;
    background-color: white;
    padding: 0.2cm;
    border-radius: 0.2cm;
    box-shadow: 0.1cm 0.1cm 0.2cm rgba(0,0,0,0.2);
    font-family: sans-serif;
    font-size: 10pt;
    z-index: 9999;
'>
    <div style="margin-bottom: 5px;"><span style="display:inline-block; width: 15px; height: 15px; background-color: #FF6600; margin-right: 8px;"></span>🚗 car</div>
    <div><span style="display:inline-block; width: 15px; height: 15px; background-color: #8ED973; margin-right: 8px;"></span>🚴‍♀️ bicycle</div>
    <div><span style="display:inline-block; width: 15px; height: 15px; background-color: #78206E; margin-right: 8px;"></span>🚌 bus</div>
    <div><span style="display:inline-block; width: 15px; height: 15px; background-color: #4E95D9; margin-right: 8px;"></span>🚶‍♂️ walk</div>
</div>
""", unsafe_allow_html=True)
