# Singapore boundary

`singapore.geojson` is the unmodified simplified Singapore ADM0 land geometry
from geoBoundaries, boundary ID `SGP-ADM0-21272760`, representing 2016 boundaries.
It includes mainland and island polygons and is used locally for GPS checks.
It is a fixed, simplified land-boundary snapshot, not a live map of reclamation
or territorial waters.

- Source: Urban Redevelopment Authority, derived from ADM3, via geoBoundaries.
- Download: https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/SGP/ADM0/geoBoundaries-SGP-ADM0_simplified.geojson
- Metadata: https://www.geoboundaries.org/api/current/gbOpen/SGP/ADM0/
- Dataset license: Open Data Commons Open Database License 1.0,
  https://opendatacommons.org/licenses/odbl/1-0/

Retrieved 2026-09-11. No geospatial package or runtime boundary download is required.

# Singapore IP ranges

`singapore_ip_ranges.txt` lists the merged IPv4/IPv6 networks that APNIC records as
allocated or assigned to Singapore (`SG`). The backend uses it offline for the graded
Singapore-only check-in rule: no student address is sent to a third-party service,
and grading without internet access behaves identically.

- Source: https://ftp.apnic.net/stats/apnic/delegated-apnic-latest (serial and MD5 in the file header;
  the MD5 was verified against APNIC's published `delegated-apnic-latest.md5`).
- Terms: freely available for use; APNIC accepts no liability for losses from use of the data.
- Limitation: the data records where blocks were first allocated, not live geolocation.
  Addresses registered elsewhere but used in Singapore (for example some cloud ranges) are rejected.
- Refresh: download the file and its `.md5`, verify, then run
  `python -m scripts.build_singapore_ip_ranges path/to/delegated-apnic-latest` from `module2-backend`.

Retrieved 2026-10-08 (APNIC serial 20261009).
