from time import sleep

from loguru import logger

from genomepy.caching import cache
from genomepy.providers.ucsc import UcscProvider
from genomepy.online import check_url, connect_ftp_link
from genomepy.providers.base import BaseProvider


class GencodeProvider(BaseProvider):
    """
    GENCODE genome provider.
    """

    name = "GENCODE"
    accession_fields = ["assembly_accession"]
    taxid_fields = ["taxonomy_id"]
    description_fields = [
        "species",
        "other_info",
    ]
    _cli_install_options = {}
    _ftp_link = "ftp.ebi.ac.uk/pub/databases/gencode"

    def __init__(self):
        self._provider_status()
        # Populate on init, so that methods can be cached
        self.genomes = get_genomes(self._ftp_link)
        self.ucsc = UcscProvider()
        self.gencode2ucsc = self.get_gencode2ucsc()
        self.update_genomes()

    @staticmethod
    def ping():
        """Can the provider be reached?"""
        return bool(check_url("ftp.ebi.ac.uk/pub/databases/gencode"))

    def _genome_info_tuple(self, name):
        """tuple with assembly metadata"""
        accession = self.genomes[name]["assembly_accession"]
        taxid = self.genomes[name]["taxonomy_id"]
        annotations = True
        species = self.genomes[name]["species"]
        other = self.genomes[name]["other_info"]
        return name, accession, taxid, annotations, species, other

    def get_gencode2ucsc(self):
        # start with historic assemblies
        gencode2ucsc = {
            "GRCh37": "hg19",
            "GRCm38": "mm10",
            "GRCm37": "mm9",
        }
        # add latest assemblies
        for assembly in self.genomes:
            if assembly not in gencode2ucsc:
                specie = self.genomes[assembly]["species"]
                specie = "hg" if specie == "Homo sapiens" else "mm"
                number = "".join([s for s in assembly if s.isdigit()])
                ucsc_assembly = f"{specie}{number}"
                gencode2ucsc[assembly] = ucsc_assembly
        return gencode2ucsc

    def update_genomes(self):
        for name in self.genomes:
            ucsc_name = self.gencode2ucsc[name]
            # makes the genome findable with UCSC names
            self.genomes[name]["other_info"] = f"GENCODE annotation + UCSC {ucsc_name} genome"
            ucsc_acc = self.ucsc.genomes[ucsc_name]["assembly_accession"]
            self.genomes[name]["assembly_accession"] = ucsc_acc

    def get_genome_download_link(self, name, mask="soft", **kwargs):
        ucsc_name = self.gencode2ucsc[name]
        return self.ucsc.get_genome_download_link(ucsc_name, mask, **kwargs)

    def download_genome(
            self,
            name: str,
            genomes_dir: str = None,
            localname: str = None,
            mask: str = "soft",
            **kwargs,
    ):
        """
        Download genomes from UCSC, as the GENCODE genomes aren't masked.
        Contigs between the UCSC genome and GENCODE annotations match.
        """
        ucsc_name = self.gencode2ucsc[name]
        self.ucsc.name = "GENCODE"  # for logging & readme
        self.ucsc.download_genome(ucsc_name, genomes_dir, localname, mask, **kwargs)
        self.ucsc.name = "UCSC"
        # TODO: filter out contigs not present in the annotation?
        # regex = "chr(\d+|X|Y|M)"

    def get_annotation_download_links(self, name, **kwargs):
        return self.genomes[name]["annotations"]


def get_releases(listing, specie):
    # ignore releases without a consistent system.
    releases = [int(ftpdir[-2:]) for ftpdir in listing if ftpdir[-2:].isdigit()]
    releases = sorted([str(n) for n in releases if n > 21], reverse=True)
    if specie == "mouse":
        releases = ["M" + r for r in releases]  # dear gencode: why?
    return releases


@cache
def get_genomes(ftp_link):
    logger.info("Downloading assembly summaries from GENCODE")

    genomes = {}
    species = {
        "human": "Homo sapiens",
        "mouse": "Mus musculus"
    }
    taxid = {
        "human": 9606,
        "mouse": 10090
    }
    sleep(1)  # we just closed a connection with ping()
    ftp, ftp_path = connect_ftp_link(ftp_link)
    for specie in ["human", "mouse"]:
        listing = ftp.nlst(f"{ftp_path}/Gencode_{specie}")
        releases = get_releases(listing, specie)
        for release in releases:
            species_basepath = f"{ftp_link}/Gencode_{specie}/release_{release}"
            listing = ftp.nlst(f"{ftp_path}/Gencode_{specie}/release_{release}")
            files = [f.split("/")[-1] for f in listing]
            # drop patch level (UCSC genomes don't have patches either)
            assembly = [f for f in files if "primary_assembly" in f][0].split(".")[0]
            if assembly not in genomes:
                genomes[assembly] = {
                    "annotations": [f"{species_basepath}/gencode.v{release}.annotation.gtf.gz"],
                    "taxonomy_id": taxid[specie],
                    "species": species[specie],
                }

            if specie == "human" and "GRCh37" not in genomes and "GRCh37_mapping" in files:
                genomes["GRCh37"] = {
                    "annotations": [f"{species_basepath}/GRCh37_mapping/gencode.v{release}lift37.annotation.gtf.gz"],
                    "taxonomy_id": 9606,
                    "species": "Homo sapiens",
                }
    ftp.quit()
    return genomes