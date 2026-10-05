"""Trader Joe's DC lookup.

The DC # column in Smartsheet holds Business Central's Destination No.
(ship-to code). Each code maps to one TJ appointment location. Dry, cooler
and temp control at the same building share one email and one set of days;
mixing centers have their own.

Allowed days come from Trader_Joes_DC_List_2026.xlsx (Irving Cooler typo
fixed: Irving is Mon/Wed/Thu/Fri for every DC type).
Weekdays: 0=Mon ... 6=Sun.
"""

MON, TUE, WED, THU, FRI = 0, 1, 2, 3, 4

LOCATIONS = {
    # Mixing centers
    "kentucky_mc":   {"name": "Kentucky Mixing Center",   "tj_dcs": "6450", "city": "Franklin, KY",       "email": "Kentucky_PCC_Vendor_Appointments@wcdinc.net",             "days": [MON, THU]},
    "virginia_mc":   {"name": "Virginia Mixing Center",   "tj_dcs": "6700", "city": "Ruther Glen, VA",    "email": "Virginia_MixingCenter_Vendor_Appointments@wcdinc.net",   "days": [MON, THU, FRI]},
    "palmdale_mc":   {"name": "Palmdale Mixing Center",   "tj_dcs": "6020", "city": "Palmdale, CA",       "email": "Palmdale_MixingCenter_Vendor_Appointments@wcdinc.net",   "days": [TUE, WED, THU, FRI]},
    "stockton_mc":   {"name": "Stockton Mixing Center",   "tj_dcs": "6050", "city": "Stockton, CA",       "email": "Stockton_MixingCenter_Vendor_Appointments@wcdinc.net",   "days": [TUE, WED, THU, FRI]},
    "sacramento_mc": {"name": "Sacramento Mixing Center", "tj_dcs": "6070", "city": "Rancho Cordova, CA", "email": "Sacramento_MixingCenter_Vendor_Appointments@wcdinc.net", "days": [TUE, WED, THU, FRI]},
    "allentown_mc":  {"name": "Allentown Mixing Center",  "tj_dcs": "6500", "city": "Nazareth, PA",       "email": "Allentown_MixingCenter_Vendor_Appointments@wcdinc.net",  "days": [MON, THU, FRI]},
    # Regular DCs (dry / cooler / temp control share email + days)
    "allentown":  {"name": "Allentown",  "tj_dcs": "5503 / 5504 / 5507", "city": "Nazareth, PA",       "email": "allentown_vendor_appointments@wcdinc.net",  "days": [MON, THU, FRI]},
    "virginia":   {"name": "Virginia",   "tj_dcs": "5703 / 5704 / 5707", "city": "Ruther Glen, VA",    "email": "caroline_vendor_appointments@wcdinc.net",   "days": [MON, THU, FRI]},
    "minooka":    {"name": "Minooka",    "tj_dcs": "5353 / 5354 / 5357", "city": "Minooka, IL",        "email": "minooka_vendor_appointments@wcdinc.net",    "days": [MON, WED, THU, FRI]},
    "fontana":    {"name": "Fontana",    "tj_dcs": "5003 / 5004 / 5007", "city": "Fontana, CA",        "email": "Fontana_Vendor_Appointments@wcdinc.net",    "days": [TUE, WED, THU, FRI]},
    "chino":      {"name": "Chino",      "tj_dcs": "5043",               "city": "Chino, CA",          "email": "Chino_Vendor_Appointments@wcdinc.net",      "days": [TUE, WED, THU, FRI]},
    "stockton":   {"name": "Stockton",   "tj_dcs": "5053 / 5054 / 5057", "city": "Stockton, CA",       "email": "Stockton_Vendor_Appointments@wcdinc.net",   "days": [TUE, WED, THU, FRI]},
    "lacey":      {"name": "Lacey",      "tj_dcs": "5103 / 5104 / 5107", "city": "Lacey, WA",          "email": "Lacey_Vendor_Appointments@wcdinc.net",      "days": [MON, WED, THU, FRI]},
    "irving":     {"name": "Irving",     "tj_dcs": "5303 / 5304 / 5307", "city": "Irving, TX",         "email": "Irving_Vendor_Appointments@wcdinc.net",     "days": [MON, WED, THU, FRI]},
    "daytona":    {"name": "Daytona",    "tj_dcs": "5653 / 5654 / 5657", "city": "Daytona Beach, FL",  "email": "Daytona_vendor_appointments@wcdinc.net",    "days": [MON, FRI]},
    "hartford":   {"name": "Hartford",   "tj_dcs": "5523 / 5524 / 5527", "city": "Bloomfield, CT",     "email": "hartford_vendor_appointments@wcdinc.net",   "days": [MON, FRI]},
    "redlands":   {"name": "Redlands",   "tj_dcs": "5013",               "city": "San Bernardino, CA", "email": "redlands_vendor_appointments@wcdinc.net",   "days": [TUE, WED, THU, FRI]},
    "kentucky":   {"name": "Kentucky",   "tj_dcs": "5453 / 5454 / 5457", "city": "Franklin, KY",       "email": "Kentucky_Vendor_Appointments@wcdinc.net",   "days": [MON, THU, FRI]},
    "arizona":    {"name": "Arizona",    "tj_dcs": "5163 / 5164 / 5167", "city": "Peoria, AZ",         "email": "Arizona_Vendor_Appointments@wcdinc.net",    "days": [TUE, WED, THU, FRI]},
    "palmdale":   {"name": "Palmdale",   "tj_dcs": "5023 / 5024 / 5027", "city": "Palmdale, CA",       "email": "Palmdale_Vendor_Appointments@wcdinc.net",   "days": [TUE, WED, THU, FRI]},
    "new_york":   {"name": "New York",   "tj_dcs": "5533 / 5534 / 5537", "city": "Islandia, NY",       "email": "NewYork_Vendor_Appointments@wcdinc.net",    "days": [MON, FRI]},
    "sacramento": {"name": "Sacramento", "tj_dcs": "5073 / 5074 / 5077", "city": "Rancho Cordova, CA", "email": "sacramento_vendor_appointments@wcdinc.net", "days": [TUE, WED, THU, FRI]},
    "colorado":   {"name": "Colorado",   "tj_dcs": "5203 / 5204 / 5207", "city": "Brighton, CO",       "email": "colorado_vendor_appointments@wcdinc.net",   "days": [TUE, WED, THU, FRI]},
}

# BC Destination No. -> (location key, BC name, value for the DRY/COOLER column)
BC_CODES = {
    "5617": ("sacramento",   "Sacramento Coffee & Chocolate", "COOLER"),
    "5619": ("palmdale",     "Palmdale Temp Control",         "COOLER"),
    "5621": ("kentucky",     "Kentucky Temp Control",         "COOLER"),
    "5622": ("hartford",     "Hartford Temp Control",         "COOLER"),
    "5623": ("daytona",      "Daytona Temp Control",          "COOLER"),
    "5624": ("irving",       "Irving Temp Control",           "COOLER"),
    "5625": ("allentown",    "Nazareth Dry",                  "DRY"),
    "5626": ("stockton",     "Stockton Dry",                  "DRY"),
    "5627": ("minooka",      "Minooka Temp Control",          "COOLER"),
    "5628": ("fontana",      "Fontana Temp Control",          "COOLER"),
    "5629": ("lacey",        "Lacey Temp Control",            "COOLER"),
    "5958": ("lacey",        "Lacey Dry",                     "DRY"),
    "6229": ("minooka",      "Minooka Dry",                   "DRY"),
    "6245": ("irving",       "Irving Dry",                    "DRY"),
    "6363": ("daytona",      "Daytona Dry",                   "DRY"),
    "6599": ("hartford",     "Hartford Dry",                  "DRY"),
    "6606": ("redlands",     "Redlands Dry",                  "DRY"),
    "6786": ("virginia",     "Virginia Dry",                  "DRY"),
    "6787": ("virginia",     "Caroline Temp Control",         "COOLER"),
    "6804": ("palmdale",     "Palmdale Dry",                  "DRY"),
    "6815": ("allentown",    "Nazareth Temp Control",         "COOLER"),
    "6826": ("kentucky",     "Kentucky Dry",                  "DRY"),
    "6854": ("virginia_mc",  "Virginia (Mixing Center)",      "DRY"),
    "6870": ("kentucky_mc",  "Kentucky (Mixing Center)",      "DRY"),
    "6871": ("palmdale_mc",  "Palmdale Mixing Center",        "DRY"),
    "6879": ("allentown_mc", "Nazareth Mixing Center",        "DRY"),
}

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def normalize_code(value):
    """Smartsheet returns numbers like '6599.0'; normalize to '6599'."""
    if value is None:
        return None
    s = str(value).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s or None


def resolve(dc_code):
    """Return a dict for a BC destination code, or None if unknown."""
    code = normalize_code(dc_code)
    if not code or code not in BC_CODES:
        return None
    key, bc_name, load_type = BC_CODES[code]
    loc = LOCATIONS[key]
    return {
        "code": code,
        "key": key,
        "bc_name": bc_name,
        "load_type": load_type,
        "name": loc["name"],
        "city": loc["city"],
        "email": loc["email"],
        "days": loc["days"],
        "days_label": "/".join(DAY_NAMES[d] for d in loc["days"]),
    }


def codes_for_location(key):
    return sorted(c for c, v in BC_CODES.items() if v[0] == key)
