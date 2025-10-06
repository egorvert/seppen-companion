import logging
from timezonefinder import TimezoneFinder
from geopy.geocoders import Nominatim
from langchain.tools import tool

logger = logging.getLogger(__name__)

@tool("timezone_from_location_tool")
def get_timezone_from_location(location: str) -> str:
    """
    Infers the IANA timezone from a given location string (e.g., city, country).
    Returns the timezone name (e.g., 'America/New_York') or an error message.
    """
    try:
        geolocator = Nominatim(user_agent="seppen_agent")
        location_data = geolocator.geocode(location)

        if not location_data:
            logger.warning(f"Could not find coordinates for location: {location}")
            return f"Could not determine timezone for {location}. Please ask the user for a major city or a standard timezone name."

        tf = TimezoneFinder()
        timezone_name = tf.timezone_at(lng=location_data.longitude, lat=location_data.latitude)
        
        if timezone_name:
            logger.info(f"Found timezone '{timezone_name}' for location '{location}'")
            return timezone_name
        else:
            logger.warning(f"Could not find a timezone for location: {location}")
            return f"Could not determine timezone for {location}. Please ask the user for a major city or a standard timezone name."

    except Exception as e:
        logger.error(f"Error getting timezone for location '{location}': {e}")
        return "An error occurred while trying to find the timezone." 