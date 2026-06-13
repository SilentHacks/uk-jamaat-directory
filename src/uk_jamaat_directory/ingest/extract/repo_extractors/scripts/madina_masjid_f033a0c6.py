from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    StubbedPdfExtractor,
)


class Extractor(StubbedPdfExtractor):
    key = "madina_masjid_f033a0c6"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("madinamasjidoxford.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)
    
    @property
    def targets(self):
        today = datetime.now()
        month_num = today.month
        year = today.year
        month_name = today.strftime("%B").lower()
        pdf_num = str(month_num).zfill(3)
        url = f"https://madinamasjidoxford.co.uk/wp-content/uploads/{year}/{month_num:02d}/{pdf_num}-{month_name.capitalize()}-Madina-{year}.pdf"
        
        return (
            TargetSpec(
                label="monthly_timetable",
                url=url,
                kind=TargetKind.PDF,
            ),
        )
