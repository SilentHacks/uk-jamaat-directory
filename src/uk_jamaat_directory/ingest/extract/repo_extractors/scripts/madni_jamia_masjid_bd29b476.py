"""
Madni Jamia Masjid prayer timetable extractor.

Status: SKIPPED_REVIEW
Reason: The mosque website only publishes hardcoded seasonal Jumah times
(November-March: 12:40pm, 1:20pm; April-October: 1:25pm, 2:05pm).
Daily jamaat times are embedded in a Google Sheets iframe widget that requires
JavaScript rendering. Since this is a JS-rendered target not from the allowed
widget services (athanplus, masjidal, masjidbox, mawaqit), it falls out of scope
per ADR 0017.
"""
