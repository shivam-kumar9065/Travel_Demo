# testing/functions.py

import pandas as pd
import uuid
import os

os.environ['R_HOME'] = '/usr/lib/R'
os.environ['JAVA_HOME'] = '/usr/lib/jvm/java-21-openjdk-amd64'
os.environ['LD_LIBRARY_PATH'] = '/usr/lib/jvm/java-21-openjdk-amd64/lib/server'

import rpy2
import rpy2.robjects as ro
from rpy2.robjects.packages import importr
from rpy2.robjects import r, pandas2ri, globalenv
from rpy2.robjects.vectors import StrVector, FloatVector
from rpy2.robjects import default_converter
import rpy2.robjects.conversion as conversion
from shapely.wkt import loads
import warnings
# warnings.filterwarnings('ignore')
warnings.filterwarnings("ignore", category=DeprecationWarning)
ro.r("options(warn=-1)")

# R code for optimal park and ride logic
R_OPTIMAL_PARK_AND_RIDE_LOGIC = """
    get_gtfs_dir <- function(base_data_path) {
      zip_files <- list.files(base_data_path, pattern = "\\\\.zip$", ignore.case = TRUE, full.names = TRUE)
      gtfs_zip_candidates <- character(0)
      if (length(zip_files) > 0) {
        gtfs_named_zips <- zip_files[grepl("gtfs", basename(zip_files), ignore.case = TRUE)]
        gtfs_zip_candidates <- if (length(gtfs_named_zips) > 0) gtfs_named_zips else zip_files
      }
      required_core_gtfs_files <- c("stops.txt", "stop_times.txt", "routes.txt", "trips.txt")
      check_files_exist <- function(dir_path, file_list) {
        all(sapply(file_list, function(f) length(list.files(dir_path, pattern = paste0("^", gsub("\\\\.", "\\\\\\\\.", f), "$"), ignore.case = TRUE)) > 0))
      }
      if (length(gtfs_zip_candidates) > 0) {
        selected_zip <- gtfs_zip_candidates[1]
        temp_gtfs_dir <- tempfile(pattern = "gtfs_unzipped_")
        dir.create(temp_gtfs_dir, showWarnings = FALSE)
        tryCatch(unzip(selected_zip, exdir = temp_gtfs_dir), error = function(e) stop(paste("Failed to unzip GTFS file:", selected_zip, "\\nError: ", e$message)))
        if (check_files_exist(temp_gtfs_dir, required_core_gtfs_files)) return(temp_gtfs_dir)
        subdirs_in_zip <- list.dirs(temp_gtfs_dir, recursive = FALSE, full.names = TRUE)
        for (s_dir in subdirs_in_zip) if (check_files_exist(s_dir, required_core_gtfs_files)) return(s_dir)
        unlink(temp_gtfs_dir, recursive = TRUE); stop("Unzipped GTFS archive '", selected_zip, "' but could not find required GTFS .txt files.")
      }
      if (check_files_exist(base_data_path, required_core_gtfs_files)) return(base_data_path)
      subdirs_of_base <- list.dirs(base_data_path, recursive = FALSE, full.names = TRUE)
      for (s_dir in subdirs_of_base) if (check_files_exist(s_dir, required_core_gtfs_files)) return(s_dir)
      stop("Could not find GTFS data (zip or unzipped .txt files) in or around '", base_data_path, "'.")
    }

    calculate_stop_frequencies <- function(stop_ids_to_query, gtfs_dir, current_datetime_param,
                                           time_window_minutes = 60, desired_route_types = c(0, 3)) { # time_window_minutes is transit_freq_window_min_r
      if (length(stop_ids_to_query) == 0) return(data.table(stop_id = character(0), frequency_count = integer(0)))
      stops_txt <- fread(file.path(gtfs_dir, "stops.txt")); stop_times_txt <- fread(file.path(gtfs_dir, "stop_times.txt"))
      trips_txt <- fread(file.path(gtfs_dir, "trips.txt")); routes_txt <- fread(file.path(gtfs_dir, "routes.txt"))
      calendar_txt <- if (file.exists(file.path(gtfs_dir, "calendar.txt"))) fread(file.path(gtfs_dir, "calendar.txt")) else NULL
      calendar_dates_txt <- if (file.exists(file.path(gtfs_dir, "calendar_dates.txt"))) fread(file.path(gtfs_dir, "calendar_dates.txt")) else NULL
      if (is.null(calendar_txt) && is.null(calendar_dates_txt)) stop("GTFS error: Neither calendar.txt nor calendar_dates.txt found.")
      current_date_nodash <- format(current_datetime_param, "%Y%m%d"); current_day_of_week <- tolower(weekdays(current_datetime_param))
      active_service_ids <- character(0)
      if (!is.null(calendar_txt) && current_day_of_week %in% names(calendar_txt)) {
        active_service_ids <- c(active_service_ids, calendar_txt[get(current_day_of_week) == 1 & start_date <= current_date_nodash & end_date >= current_date_nodash, service_id])
      }
      if (!is.null(calendar_dates_txt)) {
        active_service_ids <- c(active_service_ids, calendar_dates_txt[date == current_date_nodash & exception_type == 1, service_id])
        active_service_ids <- setdiff(active_service_ids, calendar_dates_txt[date == current_date_nodash & exception_type == 2, service_id])
      }
      active_service_ids <- unique(active_service_ids)
      if (length(active_service_ids) == 0) { return(data.table(stop_id = stop_ids_to_query, frequency_count = 0)) }
      relevant_routes <- routes_txt[route_type %in% desired_route_types, route_id]
      active_trips <- trips_txt[service_id %in% active_service_ids & route_id %in% relevant_routes, trip_id]
      if (length(active_trips) == 0) { return(data.table(stop_id = stop_ids_to_query, frequency_count = 0)) }
      window_end_datetime <- current_datetime_param + lubridate::minutes(time_window_minutes) # Uses the parameter
      service_day_midnight_posix <- floor_date(current_datetime_param, unit = "day")
      stop_times_txt[, departure_time_char := as.character(departure_time)]
      stop_times_txt[, departure_s_since_midnight := sapply(strsplit(departure_time_char, ":", fixed = TRUE), function(p) {
        if (length(p) == 3 && !any(is.na(as.numeric(p)))) as.numeric(p[1])*3600 + as.numeric(p[2])*60 + as.numeric(p[3]) else NA_real_ })]
      stop_times_txt <- stop_times_txt[!is.na(departure_s_since_midnight)]
      stop_times_txt[, departure_posix := service_day_midnight_posix + lubridate::seconds(departure_s_since_midnight)]
      relevant_stop_times <- stop_times_txt[stop_id %in% stop_ids_to_query & trip_id %in% active_trips & !is.na(departure_posix) & departure_posix >= current_datetime_param & departure_posix < window_end_datetime]
      if (nrow(relevant_stop_times) == 0) { return(data.table(stop_id = stop_ids_to_query, frequency_count = 0)) }
      stop_frequencies_calculated <- relevant_stop_times[, .(frequency_count = .N), by = stop_id]
      all_stops_dt <- data.table(stop_id = stop_ids_to_query)
      stop_frequencies_final <- merge(all_stops_dt, stop_frequencies_calculated, by = "stop_id", all.x = TRUE)
      stop_frequencies_final[is.na(frequency_count), frequency_count := 0]; return(stop_frequencies_final)
    }

    park_points_all <- fread(file.path(data_path_r, "bike_park_metz.csv"))
    if (!all(c("id", "lon", "lat") %in% names(park_points_all))) stop("Parking CSV must have 'id', 'lon', 'lat' columns.")
    park_points_all[, id := as.character(id)][, lon := as.numeric(lon)][, lat := as.numeric(lat)]
    bike_parking_points <- unique(na.omit(park_points_all, cols = c("id", "lon", "lat")), by = "id")
    if (nrow(bike_parking_points) == 0) stop("No valid parking points loaded after cleaning.")

    ttm_origin_to_park <- travel_time_matrix(
        r5r_core = .GlobalEnv$r5r_core_glob,
        origins = .GlobalEnv$origin_r, 
        destinations = bike_parking_points,
        mode = .GlobalEnv$access_mode_r, 
        max_trip_duration = .GlobalEnv$max_access_time_min_r + 5, 
        departure_datetime = .GlobalEnv$departure_datetime_r, 
        progress = FALSE
    )
    if (is.null(ttm_origin_to_park) || nrow(ttm_origin_to_park) == 0) stop(paste0("No parking points reachable by ", .GlobalEnv$access_mode_r, " from origin."))
    time_col_name_from_r5r <- if ("travel_time_p50" %in% names(ttm_origin_to_park)) "travel_time_p50" else "travel_time"
    setnames(ttm_origin_to_park, c("from_id", "to_id", time_col_name_from_r5r), c("from_id_origin", "to_id_park", "travel_time_access_min"))

    reachable_parking_ids <- ttm_origin_to_park[travel_time_access_min <= .GlobalEnv$max_access_time_min_r, to_id_park]
    favorable_parking_points <- bike_parking_points[id %in% reachable_parking_ids]
    if (nrow(favorable_parking_points) == 0) stop(paste0("No parking points reachable within ", .GlobalEnv$max_access_time_min_r, " minutes by ", .GlobalEnv$access_mode_r, "."))
    favorable_parking_points_sf <- st_as_sf(favorable_parking_points, coords = c("lon", "lat"), crs = 4326)

    snapped_network_locs_raw <- find_snap(r5r_core = .GlobalEnv$r5r_core_glob, points = favorable_parking_points_sf)
    if (is.null(snapped_network_locs_raw) || nrow(snapped_network_locs_raw) == 0) stop("find_snap (to network) returned no results.")
    snapped_network_locs_dt <- as.data.table(snapped_network_locs_raw)
    if (!"point_id" %in% names(snapped_network_locs_dt)) stop("find_snap output missing 'point_id'.")
    if (!all(c("snap_lat", "snap_lon") %in% names(snapped_network_locs_dt))) stop("find_snap output missing 'snap_lat'/'snap_lon'.")
    setnames(snapped_network_locs_dt, "point_id", "id")
    snapped_network_origins_sf <- st_as_sf(snapped_network_locs_dt[!is.na(snap_lat) & !is.na(snap_lon)], coords = c("snap_lon", "snap_lat"), crs = 4326)
    if (nrow(snapped_network_origins_sf) == 0) stop("No valid snapped network locations for transit stop search.")

    gtfs_parsed_dir <- get_gtfs_dir(.GlobalEnv$data_path_r) 
    gtfs_stops_dt <- fread(file.path(gtfs_parsed_dir, "stops.txt"))
    if (!"id" %in% names(gtfs_stops_dt) && "stop_id" %in% names(gtfs_stops_dt)) setnames(gtfs_stops_dt, "stop_id", "id")
    if (!"id" %in% names(gtfs_stops_dt)) stop("GTFS stops.txt needs 'id' or 'stop_id' column.")
    if (!all(c("stop_lon", "stop_lat") %in% names(gtfs_stops_dt))) stop("GTFS stops.txt needs 'stop_lon'/'stop_lat'.")
    setnames(gtfs_stops_dt, c("stop_lon", "stop_lat"), c("lon", "lat"), skip_absent = TRUE)
    gtfs_stops_for_r5r <- gtfs_stops_dt[, .(id, lon, lat)]
    walk_times_to_stops <- travel_time_matrix(
        r5r_core = .GlobalEnv$r5r_core_glob,
        origins = snapped_network_origins_sf,
        destinations = gtfs_stops_for_r5r,
        mode = "WALK",
        max_trip_duration = .GlobalEnv$max_walk_to_stop_min_r,
        departure_datetime = .GlobalEnv$departure_datetime_r,
        progress = FALSE
    )
    if (is.null(walk_times_to_stops) || nrow(walk_times_to_stops) == 0) stop(paste0("No transit stops found within ", .GlobalEnv$max_walk_to_stop_min_r, " mins walk."))
    time_col_name_from_r5r_walk <- if ("travel_time_p50" %in% names(walk_times_to_stops)) "travel_time_p50" else "travel_time"
    setnames(walk_times_to_stops, c("from_id", "to_id", time_col_name_from_r5r_walk), c("from_id_park", "to_id_stop", "walk_time_to_stop_min"))

    unique_snapped_stop_ids <- unique(walk_times_to_stops$to_id_stop)
    
    # Use .GlobalEnv$transit_freq_window_min_r when calling calculate_stop_frequencies
    stop_frequencies <- calculate_stop_frequencies(unique_snapped_stop_ids, gtfs_parsed_dir, .GlobalEnv$departure_datetime_r, .GlobalEnv$transit_freq_window_min_r)
    snapped_stops_with_freq <- merge(walk_times_to_stops, stop_frequencies, by.x = "to_id_stop", by.y = "stop_id", all.x = TRUE)
    snapped_stops_with_freq[is.na(frequency_count), frequency_count := 0]
    parking_best_stop_quality <- snapped_stops_with_freq[order(from_id_park, -frequency_count, walk_time_to_stop_min)]
    parking_best_stop_quality <- parking_best_stop_quality[!duplicated(from_id_park)]
    setnames(parking_best_stop_quality, c("to_id_stop", "walk_time_to_stop_min", "frequency_count"), c("best_stop_id", "walk_time_to_best_stop_min", "best_stop_frequency"))
    parking_best_stop_quality <- parking_best_stop_quality[, .(from_id_park, best_stop_id, walk_time_to_best_stop_min, best_stop_frequency)]

    ttm_park_to_dest <- travel_time_matrix(
        r5r_core = .GlobalEnv$r5r_core_glob,
        origins = favorable_parking_points,
        destinations = .GlobalEnv$destination_r, 
        mode = c("WALK", "TRANSIT"),
        max_trip_duration = 100,
        departure_datetime = .GlobalEnv$departure_datetime_r,
        progress = FALSE
    )
    if (is.null(ttm_park_to_dest) || nrow(ttm_park_to_dest) == 0) stop("No transit routes from favorable parking to final destination.")
    time_col_name_from_r5r_pt <- if ("travel_time_p50" %in% names(ttm_park_to_dest)) "travel_time_p50" else "travel_time"
    setnames(ttm_park_to_dest, c("from_id", "to_id", time_col_name_from_r5r_pt), c("from_id_park_dest", "to_id_dest", "travel_time_pt_min"))

    merged_times <- merge(ttm_origin_to_park[, .(id = to_id_park, travel_time_access_min)], favorable_parking_points[, .(id, lon, lat)], by = "id")
    merged_times <- merge(merged_times, parking_best_stop_quality, by.x = "id", by.y = "from_id_park", all.x = TRUE)
    if (!is.double(merged_times$walk_time_to_best_stop_min) && "walk_time_to_best_stop_min" %in% names(merged_times)) {
      merged_times[, walk_time_to_best_stop_min := as.double(walk_time_to_best_stop_min)]
    }
    merged_times[is.na(best_stop_frequency), best_stop_frequency := 0]
    merged_times[is.na(walk_time_to_best_stop_min), walk_time_to_best_stop_min := Inf]
    merged_times <- merge(merged_times, ttm_park_to_dest[, .(id = from_id_park_dest, travel_time_pt_min)], by = "id", all.x = TRUE)
    merged_times[is.na(travel_time_pt_min), travel_time_pt_min := Inf]
    merged_times[, total_travel_time_min := travel_time_access_min + travel_time_pt_min]
    merged_times_filtered <- merged_times[total_travel_time_min < Inf & walk_time_to_best_stop_min < Inf]
    if (nrow(merged_times_filtered) == 0) stop("No valid park-and-ride options found after merging all criteria.")
    setorderv(merged_times_filtered, c("total_travel_time_min", "best_stop_frequency", "walk_time_to_best_stop_min"), c(1, -1, 1))
    optimal_parking_info <- merged_times_filtered[1]
    if (is.na(optimal_parking_info$id)) stop("Could not determine an optimal parking point from filtered options.")
    optimal_parking_id <- optimal_parking_info$id
    optimal_parking <- bike_parking_points[id == optimal_parking_id]

    det_origin_to_optimal_parking <- detailed_itineraries(
        r5r_core = .GlobalEnv$r5r_core_glob,
        origins = .GlobalEnv$origin_r,
        destinations = optimal_parking,
        mode = .GlobalEnv$access_mode_r,
        departure_datetime = .GlobalEnv$departure_datetime_r,
        max_walk_time = .GlobalEnv$max_walk_time_itinerary_min_r,
        shortest_path = TRUE
    )
    det_parking_to_destination <- detailed_itineraries(
        r5r_core = .GlobalEnv$r5r_core_glob,
        origins = optimal_parking,
        destinations = .GlobalEnv$destination_r,
        mode = c("WALK", "TRANSIT"),
        departure_datetime = .GlobalEnv$departure_datetime_r,
        max_walk_time = .GlobalEnv$max_walk_time_itinerary_min_r,
        shortest_path = TRUE
    )

    det_df_final <- data.frame() 

    if (!is.null(det_origin_to_optimal_parking) && nrow(det_origin_to_optimal_parking) > 0 &&
        !is.null(det_parking_to_destination) && nrow(det_parking_to_destination) > 0) {

        dt1 <- as.data.table(det_origin_to_optimal_parking)
        if ("geometry" %in% names(dt1) && inherits(det_origin_to_optimal_parking$geometry, "sfc")) {
            dt1[, geometry_wkt := sf::st_as_text(det_origin_to_optimal_parking$geometry)]
            dt1[, geometry := NULL]
        } else if ("geometry" %in% names(dt1) && is.character(dt1$geometry)) {
            setnames(dt1, "geometry", "geometry_wkt")
        }

        dt2 <- as.data.table(det_parking_to_destination)
        if ("geometry" %in% names(dt2) && inherits(det_parking_to_destination$geometry, "sfc")) {
            dt2[, geometry_wkt := sf::st_as_text(det_parking_to_destination$geometry)]
            dt2[, geometry := NULL]
        } else if ("geometry" %in% names(dt2) && is.character(dt2$geometry)) {
            setnames(dt2, "geometry", "geometry_wkt")
        }

        det_combined_dt <- rbind(dt1, dt2, fill = TRUE)
        det_df_final <- as.data.frame(det_combined_dt) # This will be in .GlobalEnv after R string execution
    }
"""

# Global variable to track if r5r_core is initialized in R's globalenv
R5R_CORE_INITIALIZED = False


def process_r5r(data_path, origin_str, destination_str, 
                walk_time = 20, bicycle_time = 20, max_trip_duration = 120, car_time = 5,
                transit_freq_window_min = 60): # New parameter
    global R5R_CORE_INITIALIZED

    ro.r('options(java.parameters = "-Xmx12G")')

    if not os.path.exists(data_path):
        raise FileNotFoundError(f"The data path {data_path} does not exist. Please verify the path.")

    if not R5R_CORE_INITIALIZED:
        print("Initializing r5r_core in R's global environment for the first time...")
        ro.r("library(r5r)") 
        formatted_data_path = data_path.replace('\\', '/')
        ro.r(f".GlobalEnv$r5r_core_glob <- setup_r5(data_path = '{formatted_data_path}', verbose = FALSE)")
        R5R_CORE_INITIALIZED = True
    
    origin_coords = origin_str.split(',')
    destination_coords = destination_str.split(',')

    lat_ori = float(origin_coords[0])
    lon_ori = float(origin_coords[1])
    lat_des = float(destination_coords[0])
    lon_des = float(destination_coords[1])

    globalenv['lat_ori_r_glob'] = lat_ori 
    globalenv['lon_ori_r_glob'] = lon_ori
    globalenv['lat_des_r_glob'] = lat_des
    globalenv['lon_des_r_glob'] = lon_des
    globalenv['departure_datetime_str_glob'] = "12-08-2024 07:00:00" 
    globalenv['walk_time_r_glob'] = float(walk_time)
    globalenv['max_trip_duration_r_glob'] = float(max_trip_duration)

    # -------- WALK + TRANSIT --------
    ro.r(f"""
    library(r5r)
    library(data.table)
    origin_r_dt_direct_wt <- data.table(id = "origin", lat = .GlobalEnv$lat_ori_r_glob, lon = .GlobalEnv$lon_ori_r_glob)
    destination_r_dt_direct_wt <- data.table(id = "destination", lat = .GlobalEnv$lat_des_r_glob, lon = .GlobalEnv$lon_des_r_glob)
    departure_datetime_r_obj_wt <- as.POSIXct(.GlobalEnv$departure_datetime_str_glob, format = "%d-%m-%Y %H:%M:%S", tz = "Europe/Paris")
    mode_walk_transit_r <- c("WALK", "TRANSIT")
    
    .GlobalEnv$detailed_itinerary_wt <- detailed_itineraries(
        .GlobalEnv$r5r_core_glob,
        origins = origin_r_dt_direct_wt,
        destinations = destination_r_dt_direct_wt,
        mode = mode_walk_transit_r,
        departure_datetime = departure_datetime_r_obj_wt,
        max_walk_time = .GlobalEnv$walk_time_r_glob,
        max_trip_duration = .GlobalEnv$max_trip_duration_r_glob,
        shortest_path = FALSE 
    )
    """)
    try:
        pandas2ri.activate()
    except DeprecationWarning:
        pass  # Ignore deprecation error so FastAPI doesn't return 500

    ro.r('if(exists("detailed_itinerary_wt", envir = .GlobalEnv) && nrow(.GlobalEnv$detailed_itinerary_wt) > 0 && "geometry" %in% names(.GlobalEnv$detailed_itinerary_wt) && inherits(.GlobalEnv$detailed_itinerary_wt$geometry, "sfc") ) {{ .GlobalEnv$detailed_itinerary_wt$geometry_wkt <- sf::st_as_text(.GlobalEnv$detailed_itinerary_wt$geometry); .GlobalEnv$detailed_itinerary_wt$geometry <- NULL }} else if (exists("detailed_itinerary_wt", envir = .GlobalEnv) && nrow(.GlobalEnv$detailed_itinerary_wt) > 0 && "geometry" %in% names(.GlobalEnv$detailed_itinerary_wt) && is.character(.GlobalEnv$detailed_itinerary_wt$geometry) ) {{ setnames(.GlobalEnv$detailed_itinerary_wt, "geometry", "geometry_wkt") }} else if (exists("detailed_itinerary_wt", envir = .GlobalEnv) && nrow(.GlobalEnv$detailed_itinerary_wt) > 0) {{ .GlobalEnv$detailed_itinerary_wt$geometry_wkt <- NA_character_ }} else if (exists("detailed_itinerary_wt", envir = .GlobalEnv)) {{ .GlobalEnv$detailed_itinerary_wt$geometry_wkt <- character(0) }} else {{ .GlobalEnv$detailed_itinerary_wt <- data.frame(geometry_wkt=character(0)) }}')

    ro.r('if(exists("detailed_itinerary_wt", envir = .GlobalEnv)) {{ .GlobalEnv$detailed_itinerary_wt <- as.data.frame(.GlobalEnv$detailed_itinerary_wt) }} else {{ .GlobalEnv$detailed_itinerary_wt <- data.frame() }}')

    detailed_itinerary_df_walk_transit = pandas2ri.rpy2py(ro.r('.GlobalEnv$detailed_itinerary_wt'))

    if 'geometry_wkt' in detailed_itinerary_df_walk_transit.columns:
        detailed_itinerary_df_walk_transit.rename(columns={'geometry_wkt': 'geometry'}, inplace=True)


    # -------- CAR --------
    ro.r(f"""
    library(r5r)
    library(data.table)
    origin_r_dt_direct_c <- data.table(id = "origin", lat = .GlobalEnv$lat_ori_r_glob, lon = .GlobalEnv$lon_ori_r_glob)
    destination_r_dt_direct_c <- data.table(id = "destination", lat = .GlobalEnv$lat_des_r_glob, lon = .GlobalEnv$lon_des_r_glob)
    departure_datetime_r_obj_c <- as.POSIXct(.GlobalEnv$departure_datetime_str_glob, format = "%d-%m-%Y %H:%M:%S", tz = "Europe/Paris")
    mode_car_r <- "CAR"

    .GlobalEnv$detailed_itinerary_c <- detailed_itineraries(
        .GlobalEnv$r5r_core_glob,
        origins = origin_r_dt_direct_c,
        destinations = destination_r_dt_direct_c,
        mode = mode_car_r,
        departure_datetime = departure_datetime_r_obj_c,
        max_trip_duration = .GlobalEnv$max_trip_duration_r_glob, 
        shortest_path = TRUE 
    )
    """)
    ro.r('if(exists("detailed_itinerary_c", envir = .GlobalEnv) && nrow(.GlobalEnv$detailed_itinerary_c) > 0 && "geometry" %in% names(.GlobalEnv$detailed_itinerary_c) && inherits(.GlobalEnv$detailed_itinerary_c$geometry, "sfc") ) {{ .GlobalEnv$detailed_itinerary_c$geometry_wkt <- sf::st_as_text(.GlobalEnv$detailed_itinerary_c$geometry); .GlobalEnv$detailed_itinerary_c$geometry <- NULL }} else if (exists("detailed_itinerary_c", envir = .GlobalEnv) && nrow(.GlobalEnv$detailed_itinerary_c) > 0 && "geometry" %in% names(.GlobalEnv$detailed_itinerary_c) && is.character(.GlobalEnv$detailed_itinerary_c$geometry) ) {{ setnames(.GlobalEnv$detailed_itinerary_c, "geometry", "geometry_wkt") }} else if (exists("detailed_itinerary_c", envir = .GlobalEnv) && nrow(.GlobalEnv$detailed_itinerary_c) > 0) {{ .GlobalEnv$detailed_itinerary_c$geometry_wkt <- NA_character_ }} else if(exists("detailed_itinerary_c", envir = .GlobalEnv)) {{ .GlobalEnv$detailed_itinerary_c$geometry_wkt <- character(0) }} else {{ .GlobalEnv$detailed_itinerary_c <- data.frame(geometry_wkt=character(0)) }}')
    ro.r('if(exists("detailed_itinerary_c", envir = .GlobalEnv)) {{ .GlobalEnv$detailed_itinerary_c <- as.data.frame(.GlobalEnv$detailed_itinerary_c) }} else {{ .GlobalEnv$detailed_itinerary_c <- data.frame() }}')
    detailed_itinerary_df_car = pandas2ri.rpy2py(ro.r('.GlobalEnv$detailed_itinerary_c'))
    if 'geometry_wkt' in detailed_itinerary_df_car.columns:
        detailed_itinerary_df_car.rename(columns={'geometry_wkt': 'geometry'}, inplace=True)

    # -------- BICYCLE --------
    ro.r(f"""
    library(r5r)
    library(data.table)
    origin_r_dt_direct_b <- data.table(id = "origin", lat = .GlobalEnv$lat_ori_r_glob, lon = .GlobalEnv$lon_ori_r_glob)
    destination_r_dt_direct_b <- data.table(id = "destination", lat = .GlobalEnv$lat_des_r_glob, lon = .GlobalEnv$lon_des_r_glob)
    departure_datetime_r_obj_b <- as.POSIXct(.GlobalEnv$departure_datetime_str_glob, format = "%d-%m-%Y %H:%M:%S", tz = "Europe/Paris")
    mode_bicycle_r <- "BICYCLE"

    .GlobalEnv$detailed_itinerary_b <- detailed_itineraries(
        .GlobalEnv$r5r_core_glob,
        origins = origin_r_dt_direct_b,
        destinations = destination_r_dt_direct_b,
        mode = mode_bicycle_r,
        departure_datetime = departure_datetime_r_obj_b,
        max_trip_duration = .GlobalEnv$max_trip_duration_r_glob, 
        shortest_path = TRUE 
    )
    """)
    ro.r('if(exists("detailed_itinerary_b", envir = .GlobalEnv) && nrow(.GlobalEnv$detailed_itinerary_b) > 0 && "geometry" %in% names(.GlobalEnv$detailed_itinerary_b) && inherits(.GlobalEnv$detailed_itinerary_b$geometry, "sfc") ) {{ .GlobalEnv$detailed_itinerary_b$geometry_wkt <- sf::st_as_text(.GlobalEnv$detailed_itinerary_b$geometry); .GlobalEnv$detailed_itinerary_b$geometry <- NULL }} else if (exists("detailed_itinerary_b", envir = .GlobalEnv) && nrow(.GlobalEnv$detailed_itinerary_b) > 0 && "geometry" %in% names(.GlobalEnv$detailed_itinerary_b) && is.character(.GlobalEnv$detailed_itinerary_b$geometry) ) {{ setnames(.GlobalEnv$detailed_itinerary_b, "geometry", "geometry_wkt") }} else if (exists("detailed_itinerary_b", envir = .GlobalEnv) && nrow(.GlobalEnv$detailed_itinerary_b) > 0) {{ .GlobalEnv$detailed_itinerary_b$geometry_wkt <- NA_character_ }} else if(exists("detailed_itinerary_b", envir = .GlobalEnv)) {{ .GlobalEnv$detailed_itinerary_b$geometry_wkt <- character(0) }} else {{ .GlobalEnv$detailed_itinerary_b <- data.frame(geometry_wkt=character(0)) }}')
    ro.r('if(exists("detailed_itinerary_b", envir = .GlobalEnv)) {{ .GlobalEnv$detailed_itinerary_b <- as.data.frame(.GlobalEnv$detailed_itinerary_b) }} else {{ .GlobalEnv$detailed_itinerary_b <- data.frame() }}')
    detailed_itinerary_df_bicycle = pandas2ri.rpy2py(ro.r('.GlobalEnv$detailed_itinerary_b'))
    if 'geometry_wkt' in detailed_itinerary_df_bicycle.columns:
        detailed_itinerary_df_bicycle.rename(columns={'geometry_wkt': 'geometry'}, inplace=True)

    globalenv['data_path_r'] = data_path 
    # Create departure_datetime_r in R's global environment once for the optimal park & ride logic
    ro.r(".GlobalEnv$departure_datetime_r <- as.POSIXct(.GlobalEnv$departure_datetime_str_glob, format = '%d-%m-%Y %H:%M:%S', tz = 'Europe/Paris')")
    # CORRECTED: Use the Python function parameter transit_freq_window_min
    globalenv['transit_freq_window_min_r'] = float(transit_freq_window_min) 
    globalenv['max_walk_time_itinerary_min_r'] = float(walk_time) 
    
    # -------- BICYCLE + TRANSIT (Optimal Parking) --------
    globalenv['max_access_time_min_r'] = float(bicycle_time) 
    globalenv['max_walk_to_stop_min_r'] = float(walk_time) 
    globalenv['access_mode_r'] = "BICYCLE"
    ro.r("""
    .GlobalEnv$origin_r <- data.table(id = "origin", lat = .GlobalEnv$lat_ori_r_glob, lon = .GlobalEnv$lon_ori_r_glob)
    .GlobalEnv$destination_r <- data.table(id = "destination", lat = .GlobalEnv$lat_des_r_glob, lon = .GlobalEnv$lon_des_r_glob)
    """)
    ro.r(f"""
    library(r5r); library(sf); library(data.table); library(lubridate)
    {R_OPTIMAL_PARK_AND_RIDE_LOGIC}
    """)
    detailed_itinerary_df_bicycle_transit = pandas2ri.rpy2py(ro.r('.GlobalEnv$det_df_final'))
    if 'geometry_wkt' in detailed_itinerary_df_bicycle_transit.columns:
        detailed_itinerary_df_bicycle_transit.rename(columns={'geometry_wkt': 'geometry'}, inplace=True)

    # -------- CAR + TRANSIT (Optimal Parking) --------
    globalenv['max_access_time_min_r'] = float(car_time) 
    globalenv['max_walk_to_stop_min_r'] = float(walk_time) 
    globalenv['access_mode_r'] = "CAR"
    ro.r("""
    .GlobalEnv$origin_r <- data.table(id = "origin", lat = .GlobalEnv$lat_ori_r_glob, lon = .GlobalEnv$lon_ori_r_glob)
    .GlobalEnv$destination_r <- data.table(id = "destination", lat = .GlobalEnv$lat_des_r_glob, lon = .GlobalEnv$lon_des_r_glob)
    """)
    ro.r(f"""
    library(r5r); library(sf); library(data.table); library(lubridate)
    {R_OPTIMAL_PARK_AND_RIDE_LOGIC}
    """)
    detailed_itinerary_df_car_transit = pandas2ri.rpy2py(ro.r('.GlobalEnv$det_df_final'))
    if 'geometry_wkt' in detailed_itinerary_df_car_transit.columns:
        detailed_itinerary_df_car_transit.rename(columns={'geometry_wkt': 'geometry'}, inplace=True)
    
    # -------- Process all DataFrames --------
    det_iten_lst = []
    if detailed_itinerary_df_walk_transit is not None and not detailed_itinerary_df_walk_transit.empty:
        det_iten_lst.append(detailed_itinerary_df_walk_transit)
    if detailed_itinerary_df_car is not None and not detailed_itinerary_df_car.empty:
        det_iten_lst.append(detailed_itinerary_df_car)
    if detailed_itinerary_df_bicycle_transit is not None and not detailed_itinerary_df_bicycle_transit.empty:
         det_iten_lst.append(detailed_itinerary_df_bicycle_transit) 
    if detailed_itinerary_df_car_transit is not None and not detailed_itinerary_df_car_transit.empty:
        det_iten_lst.append(detailed_itinerary_df_car_transit) 
    if detailed_itinerary_df_bicycle is not None and not detailed_itinerary_df_bicycle.empty:
        det_iten_lst.append(detailed_itinerary_df_bicycle)

    fin_det_iten_lst = []
    for idx, det_df_current in enumerate(det_iten_lst):
        if det_df_current.empty: 
            fin_det_iten_lst.append(pd.DataFrame())
            continue
        if 'departure_time' in det_df_current.columns:
            if not pd.api.types.is_datetime64_any_dtype(det_df_current['departure_time']):
                try:
                    det_df_current['departure_time'] = pd.to_datetime(det_df_current['departure_time'], errors='coerce')
                except Exception as e:
                    print(f"Warning: Could not convert 'departure_time' to datetime for df index {idx}. Error: {e}")
        dfs_options = []
        if 'option' not in det_df_current.columns: 
            if not det_df_current.empty:
                det_df_current['option'] = 1 
            else:
                fin_det_iten_lst.append(pd.DataFrame()) 
                continue
        options = det_df_current['option'].unique()
        for opt_val in options:
            samp_df = det_df_current[det_df_current['option'] == opt_val].copy() 
            cols_to_drop = ['total_duration', 'total_distance']
            existing_cols_to_drop = [col for col in cols_to_drop if col in samp_df.columns]
            if existing_cols_to_drop:
                samp_df = samp_df.drop(columns=existing_cols_to_drop)
            if 'geometry' in samp_df.columns and not samp_df['geometry'].empty and samp_df['geometry'].iloc[0] is not None:
                if isinstance(samp_df['geometry'].iloc[0], str):
                    try:
                        samp_df['geometry'] = samp_df['geometry'].apply(lambda x: loads(x) if pd.notnull(x) else None)
                    except Exception as e:
                        samp_df['geometry'] = None 
                if 'geometry' in samp_df.columns and samp_df['geometry'].iloc[0] is not None : 
                    try:
                        samp_df['from_lat'] = samp_df['geometry'].apply(lambda geom: geom.coords[0][1] if geom and hasattr(geom, 'coords') and len(geom.coords) > 0 else None)
                        samp_df['from_lon'] = samp_df['geometry'].apply(lambda geom: geom.coords[0][0] if geom and hasattr(geom, 'coords') and len(geom.coords) > 0 else None)
                        samp_df['to_lat'] = samp_df['geometry'].apply(lambda geom: geom.coords[-1][1] if geom and hasattr(geom, 'coords') and len(geom.coords) > 0 else None)
                        samp_df['to_lon'] = samp_df['geometry'].apply(lambda geom: geom.coords[-1][0] if geom and hasattr(geom, 'coords') and len(geom.coords) > 0 else None)
                    except Exception as e:
                         print(f"Error extracting coordinates for option {opt_val}: {e}")
            if 'departure_time' in samp_df.columns and 'segment_duration' in samp_df.columns and \
               pd.api.types.is_datetime64_any_dtype(samp_df['departure_time']):
                for j in range(1, len(samp_df)):
                    try:
                        segment_duration_val = pd.to_numeric(samp_df['segment_duration'].iloc[j-1], errors='coerce')
                        if pd.isna(segment_duration_val): continue 
                        segment_duration_td = pd.to_timedelta(segment_duration_val, unit='m')
                        current_departure_time = samp_df['departure_time'].iloc[j-1]
                        if pd.isna(current_departure_time): continue 
                        if samp_df['mode'].iloc[j] == 'BUS' and 'wait' in samp_df.columns:
                            wait_val = pd.to_numeric(samp_df['wait'].iloc[j], errors='coerce')
                            wait_td = pd.to_timedelta(wait_val if pd.notnull(wait_val) else 0, unit='m')
                            samp_df.loc[samp_df.index[j], 'departure_time'] = current_departure_time + segment_duration_td + wait_td
                        else: 
                             samp_df.loc[samp_df.index[j], 'departure_time'] = current_departure_time + segment_duration_td
                    except Exception as e:
                        print(f"Error processing departure time adjustment for option {opt_val}, row {j}: {e}")
            dfs_options.append(samp_df)
        if dfs_options:
            fin_df_option = pd.concat(dfs_options, ignore_index=True)
            fin_det_iten_lst.append(fin_df_option)
        elif not det_df_current.empty: 
            fin_det_iten_lst.append(det_df_current) 
    
    temp_labeled_dfs = []
    original_df_map = [
        (detailed_itinerary_df_walk_transit, "Walk+Transit"),
        (detailed_itinerary_df_car, "CAR"),
        (detailed_itinerary_df_bicycle_transit, "Bicycle+Transit"),
        (detailed_itinerary_df_car_transit, "Car+Transit"),
        (detailed_itinerary_df_bicycle, "Bicycle")
    ]
    processed_idx = 0 
    for original_df, label in original_df_map:
        if original_df is not None and not original_df.empty:
            if processed_idx < len(fin_det_iten_lst):
                current_processed_df = fin_det_iten_lst[processed_idx]
                if not current_processed_df.empty:
                    current_processed_df['Mode_Transport'] = label
                    if 'segment_duration' in current_processed_df.columns:
                        current_processed_df['segment_duration'] = pd.to_numeric(current_processed_df['segment_duration'], errors='coerce')
                        if len(current_processed_df) > 0: # Make sure there is a row 0
                            if label == "CAR":
                                current_processed_df.loc[0, 'segment_duration'] = (current_processed_df.loc[0, 'segment_duration'] if pd.notnull(current_processed_df.loc[0, 'segment_duration']) else 0) + 10
                            elif label == "Bicycle+Transit":
                                current_processed_df.loc[0, 'segment_duration'] = (current_processed_df.loc[0, 'segment_duration'] if pd.notnull(current_processed_df.loc[0, 'segment_duration']) else 0) + 5
                            elif label == "Car+Transit":
                                current_processed_df.loc[0, 'segment_duration'] = (current_processed_df.loc[0, 'segment_duration'] if pd.notnull(current_processed_df.loc[0, 'segment_duration']) else 0) + 10
                            elif label == "Bicycle":
                                current_processed_df.loc[0, 'segment_duration'] = (current_processed_df.loc[0, 'segment_duration'] if pd.notnull(current_processed_df.loc[0, 'segment_duration']) else 0) + 5
                    temp_labeled_dfs.append(current_processed_df)
                else: 
                    temp_labeled_dfs.append(pd.DataFrame())
                processed_idx += 1
            else: 
                temp_labeled_dfs.append(pd.DataFrame())
        else: 
            temp_labeled_dfs.append(pd.DataFrame())

    fin_det_iten_lst_non_empty = [df for df in temp_labeled_dfs if df is not None and not df.empty]
    if not fin_det_iten_lst_non_empty:
        print("All resulting DataFrames are empty. Returning an empty DataFrame.")
        return pd.DataFrame()

    fin_2_concat = pd.concat(fin_det_iten_lst_non_empty, ignore_index=True)
    os.makedirs("outputs", exist_ok=True)
    filename = f"trip_summary_{uuid.uuid4().hex}.csv"
    file_path = os.path.join("outputs", filename)
    fin_2_concat.to_csv(file_path, index=False)

    return file_path
