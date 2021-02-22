import gzip
import json
import os
import re
import tempfile

from tqdm import tqdm  # type: ignore
from typing import List, Dict, Any, Set, Optional, IO
from zipfile import ZipFile
import pandas as pd  # type: ignore
from prefixcommons import contract_uri # type: ignore

from kg_covid_19.transform_utils.transform import Transform
from kg_covid_19.utils import write_node_edge_item
from kg_covid_19.utils.transform_utils import unzip_to_tempdir

CUSTOM_CMAP = {
    'CHEMBL.COMPOUND': 'https://www.ebi.ac.uk/chembl/compound_report_card/',
    'MESH': 'https://id.nlm.nih.gov/mesh/',
    'UniProtKB': 'https://www.uniprot.org/uniprot/',
    'HGNC': 'http://www.genenames.org/cgi-bin/gene_symbol_report?match=',
    'WD': 'http://www.wikidata.org/entity/'
}


class ScibiteCordTransform(Transform):
    """
    ScibiteCordTransform parses the SciBite annotations on CORD-19 dataset
    to extract concept to publication annotations and co-occurrences.
    """
    def __init__(self, input_dir: str = None, output_dir: str = None):
        source_name = "SciBite-CORD-19"
        super().__init__(source_name, input_dir, output_dir)
        self.concept_name_map: Dict = {}
        self.seen: Set = set()
        self.gene_info_map: Dict = {}
        self.country_code_map: Dict = {}
        self.load_gene_info(self.input_base_dir, self.output_dir, ['9606'])
        self.load_country_code(self.input_base_dir, self.output_dir)

    def run(self,
            pdf_zipfile_1: Optional[str] = None,
            pdf_zipfile_2: Optional[str] = None,
            pmc_zipfile: Optional[str] = None,
            co_occur_zipfile: Optional[str] = None) -> None:
        """Method is called and performs needed transformations to process
        annotations from SciBite CORD-19

        Args:
            pdf_zipfile_1: PDF zip file part 1 [pdf_json_part_1.zip]
            pdf_zipfile_2: PDF zip file part 2 [pdf_json_part_1.zip]
            pmc_zipfile: pmc zipfile [pmc_json.zip]
            co_occur_zipfile: coocurrence data zipfile [cv19_scc_1_2.zip]

        Returns:
            None.
        """
        if not pdf_zipfile_1:
            pdf_zipfile_1 = os.path.join(self.input_base_dir, "pdf_json_part_1.zip")
        if not pdf_zipfile_2:
            pdf_zipfile_2 = os.path.join(self.input_base_dir, "pdf_json_part_2.zip")
        if not pmc_zipfile:
            pmc_zipfile = os.path.join(self.input_base_dir, "pmc_json.zip")
        if not co_occur_zipfile:
            co_occur_zipfile = os.path.join(self.input_base_dir, "cv19_scc_1_2.zip")

        self.node_header = ['id', 'name', 'category', 'description', 'provided_by']
        self.edge_header = ['subject', 'edge_label', 'object', 'relation', 'provided_by', 'type']
        node_handle = open(self.output_node_file, 'w')
        edge_handle = open(self.output_edge_file, 'w')
        node_handle.write("\t".join(self.node_header) + "\n")
        edge_handle.write("\t".join(self.edge_header) + "\n")
        self.parse_annotations(node_handle, edge_handle, pdf_zipfile_1, pdf_zipfile_2,
                               pmc_zipfile)

        node_handle = open(os.path.join(self.output_dir, "entity_cooccurrence_nodes.tsv"), 'w')
        edge_handle = open(os.path.join(self.output_dir, "entity_cooccurrence_edges.tsv"), 'w')
        node_handle.write("\t".join(self.node_header) + "\n")
        edge_handle.write("\t".join(self.edge_header) + "\n")
        self.parse_cooccurrence(node_handle, edge_handle, co_occur_zipfile)

    def parse_annotations(self, node_handle: IO, edge_handle: IO,
                          data_file1: str,
                          data_file2: str,
                          data_file3: str
                          ) -> None:
        """Parse annotations from CORD-19_1_5.zip.

        Args:
            node_handle: File handle for nodes.csv.
            edge_handle: File handle for edges.csv.
            data_file1: Path to pdf_json_part_1.zip
            data_file2: Path to pdf_json_part_2.zip
            data_file2: Path to pmc_json.zip

        Returns:
             None.

        """
        pbar = tqdm(total=3, desc="Unzipping files")

        # unzip to tmpdir, remove after use, to avoid cluttering raw/ with processed
        # data
        with tempfile.TemporaryDirectory(dir=self.input_base_dir) as tmpdir:
            unzip_to_tempdir(data_file1, tmpdir)
            pbar.update(1)
            unzip_to_tempdir(data_file2, tmpdir)
            pbar.update(1)
            unzip_to_tempdir(data_file3, tmpdir)
            pbar.update(1)
            pbar.close()

            subsets = ['pmc_json', 'pdf_json_part_1', 'pdf_json_part_2']
            for subset in subsets:
                subset_dir = os.path.join(tmpdir, subset)
                for filename in tqdm(os.listdir(subset_dir)):
                    if filename.startswith('.'):
                        print(f"skipping file {filename}")
                        continue
                    file = os.path.join(subset_dir, filename)
                    doc = json.load(open(file))
                    self.parse_annotation_doc(node_handle, edge_handle, doc)

    def parse_annotation_doc(self, node_handle, edge_handle, doc: Dict) -> None:
        """Parse a JSON document corresponding to a publication.

        Args:
            node_handle: File handle for nodes.csv.
            edge_handle: File handle for edges.csv.
            doc: JSON document as dict.
            subset: The subset name for this dataset.

        Returns:
            None.

        """
        terms = set()
        paper_id = doc['paper_id']
        title = None
        if 'metadata' in doc:
            metadata = doc['metadata']
            title = re.sub(r"[\n\t]", " ", metadata['title'])
            # extract hits from metadata
            terms.update(self.extract_termite_hits(metadata))

        if 'abstract' in doc:
            abstract = doc['abstract']
            # extract hits from abstract
            for x in abstract:
                terms.update(self.extract_termite_hits(x))

        if 'body_text' in doc:
            body_text = doc['body_text']
            # extract hits from body text
            for x in body_text:
                terms.update(self.extract_termite_hits(x))

        provided_by = f"{self.source_name}"

        # add a biolink:Publication for each paper
        write_node_edge_item(
            fh=node_handle,
            header=self.node_header,
            data=[
                f"CORD:{paper_id}",
                f"{title}",
                "biolink:Publication",
                "",
                self.source_name
            ]
        )
        self.seen.add(paper_id)

        for t in terms:
            if len(t) == 2:
                # country code
                if t in self.country_code_map:
                    mapped_t = self.country_code_map[t][0]
                    name = self.country_code_map[t][1]
                    curie = self.contract_uri(mapped_t)
                else:
                    name = ""
                    curie = self.contract_uri(t)
                category = 'biolink:NamedThing'
            else:
                category = 'biolink:OntologyClass'
                curie = self.contract_uri(t)
                name = self.concept_name_map[t] if t in self.concept_name_map else "",

            ###
            ###temporary solution to normalize PR: prefixes to UniProtKB
            ###

            ### requjires testing
            if re.search("^PR:\d+$", curie):
                orig = curie
                curie = re.sub("^PR:", "UniProtKB:", curie)
                print("WARNING: replaced %s with %s", orig, curie)

            if t not in self.seen:
                # add a biolink:OntologyClass node for each term
                write_node_edge_item(
                    fh=node_handle,
                    header=self.node_header,
                    data=[
                        f"{curie}",
                        name if isinstance(name, str) else "",
                        category,
                        "",
                        self.source_name
                    ]
                )
                self.seen.add(curie)

            # add has_annotation edge between OntologyClass and Publication
            write_node_edge_item(
                fh=edge_handle,
                header=self.edge_header,
                data=[
                    f"{curie}",
                    f"biolink:related_to",
                    f"CORD:{paper_id}",
                    "SIO:000255",
                    provided_by,
                    "biolink:Association"
                ]
            )

    def parse_cooccurrence(self, node_handle: Any, edge_handle: Any, data_file: str) -> None:
        """Parse term co-occurrences from cv19_scc.zip.

        Args:
            node_handle: File handle for nodes.csv.
            edge_handle: File handle for edges.csv.
            data_file: Path to cv19_scc.zip.

        Returns:
             None.

        """
        with ZipFile(data_file, 'r') as ZF, \
                tempfile.TemporaryDirectory(dir=self.input_base_dir) as tmpdir:
            ZF.extractall(path=tmpdir)
            df = pd.read_csv(os.path.join(tmpdir, 'cv19_scc.tsv'), delimiter='\t', encoding='utf-8')
        for index, row in df.iterrows():
            self.parse_cooccurrence_record(node_handle, edge_handle, row)

    def parse_cooccurrence_record(self, node_handle: Any, edge_handle: Any, record: Dict) -> None:
        """Parse term-cooccurrences.

        Args:
            node_handle: File handle for nodes.csv.
            edge_handle: File handle for edges.csv.
            record: A dictionary corresponding to a row from a table.

        Returns:
             None.

        """
        terms = set()
        paper_id = record['document_id']
        if not pd.isna(record['entity_uris']):
            terms.update(record['entity_uris'].split('|'))
            # add a biolink:Publication for each paper
            if paper_id.endswith('.xml'):
                paper_id = paper_id.replace('.xml', '')
            paper_curie = f"CORD:{paper_id}"
            if paper_id not in self.seen:
                write_node_edge_item(
                    fh=node_handle,
                    header=self.node_header,
                    data=[
                        paper_curie,
                        "",
                        "biolink:Publication",
                        "",
                        f"{self.source_name} co-occurrences"
                    ]
                )
                self.seen.add(paper_id)

            for t in terms:
                if len(t) == 2:
                    # country code
                    if t in self.country_code_map:
                        mapped_t = self.country_code_map[t][0]
                        name = self.country_code_map[t][1]
                        curie = self.contract_uri(mapped_t)
                    else:
                        name = ""
                        curie = self.contract_uri(t)
                    category = 'biolink:NamedThing'
                else:
                    category = 'biolink:OntologyClass'
                    curie = self.contract_uri(t)
                    name = self.concept_name_map[t] if t in self.concept_name_map else "",

                ###
                ###temporary solution to normalize PR: prefixes to UniProtKB
                ###

                ### requjires testing
                if re.search("^PR:\d+$", curie):
                    orig = curie
                    curie = re.sub("^PR:", "UniProtKB:", curie)
                    print("WARNING: replaced %s with %s", orig, curie)

                if t not in self.seen:
                    
                    write_node_edge_item(
                        fh=node_handle,
                        header=self.node_header,
                        data=[
                            f"{curie}",
                            name if isinstance(name, str) else "",
                            category,
                            "",
                            f"{self.source_name} co-occurrences"
                        ]
                    )
                    self.seen.add(curie)

                    # simplified generation of edges between OntologyClass and the publication where
                    # OntologyClass -> correlated_with -> Publication
                    # with the edge having relation RO:0002610
                    if (curie, paper_curie) not in self.seen:

                        write_node_edge_item(
                            fh=edge_handle,
                            header=self.edge_header,
                            data=[
                                f"{curie}",
                                "biolink:correlated_with",
                                f"{paper_curie}",
                                f"RO:0002610", # 'correlated with'
                                f"{self.source_name} co-occurrences",
                                "biolink:Association"
                            ]
                        )
                        self.seen.add((curie, paper_curie))

            # This is an earlier style of modeling that involves an InformationContentEntity for every instance of
            # co-occurrence between a Publication and a set of OntologyClass
            #
            # information_entity = uuid.uuid1()
            # write_node_edge_item(
            #     fh=node_handle,
            #     header=self.node_header,
            #     data=[
            #         f"{uuid.uuid1()}",
            #         "",
            #         "biolink:InformationContentEntity",
            #         ""
            #     ]
            # )
            # add has_annotation edge between co-occurrence entity and publication
            # write_node_edge_item(
            #     fh=edge_handle,
            #     header=self.edge_header,
            #     data=[
            #         f"{information_entity}",
            #         "biolink:related_to",
            #         f"{record['document_id']}",
            #         "SIO:000255", # 'has annotation'
            #         f"{self.source_name}"
            #     ]
            # )
            # for t in terms:
            #     curie = self.contract_uri(t)
            #     # add has_member edges between co-occurrence entity and each term
            #     write_node_edge_item(
            #         fh=edge_handle,
            #         header=self.edge_header,
            #         data=[
            #             f"{information_entity}",
            #             "biolink:related_to",
            #             f"{curie}",
            #             f"SIO:000059", # 'has member'
            #             f"{self.source_name}"
            #         ]
            #     )


    def extract_termite_hits(self, data: Dict) -> Set:
        """Parse termite hits

        Args:
            node_handle: File handle for nodes.csv.
            edge_handle: File handle for edges.csv.
            data: A dictionary.

        Returns:
             None.

        """
        terms = set()
        termite_hits = data['termite_hits']
        for k, v in termite_hits.items():
            for hit in v:
                terms.update([hit['id']])
                if hit['id'] not in self.concept_name_map:
                    self.concept_name_map[hit['id']] = hit['name']
        return terms

    def contract_uri(self, iri) -> str:
        """Contract a given IRI.

        Contract a given IRI, with special parsing and transformations
        depending on the nature of the IRI.

        Args:
            iri: IRI as string

        Returns:
            str.

        """
        curie = ""
        if 'http://www.genenames.org/cgi-bin/gene_symbol_report?match=' in iri:
            identifier = iri.split('=')[-1]
            if identifier in self.gene_info_map:
                curie = f"NCBIGene:{self.gene_info_map[identifier]['NCBI']}"
            else:
                [curie] = contract_uri(iri, cmaps=[CUSTOM_CMAP])
        else:
            if self.is_iri(iri):
                curie = contract_uri(iri)
                if curie:
                    curie = curie[0]
                else:
                    curie = contract_uri(iri, cmaps=[CUSTOM_CMAP])
                    if curie:
                        curie = curie[0]
                    else:
                        curie = iri
            elif self.is_curie(iri):
                curie = iri
            else:
                curie = f":{iri}"

        return curie

    @staticmethod
    def is_curie(s: str) -> bool:
        """Check if a given string is a CURIE.

        Args:
            s: string

        Returns:
            bool.

        """
        m = re.match(r"^[^ :]+:[^/ :]+$", s)
        return bool(m)

    @staticmethod
    def is_iri(s) -> bool:
        """Check ig a given string is an IRI.

        Args:
            s: string

        Returns:
            bool.

        """
        m = re.match(r"^http[s]?://", s)
        return bool(m)

    def load_gene_info(self, input_dir: str, output_dir: str, species_id: List = None) -> None:
        """Load mappings from NCBI gene_info (gene_info.gz).

        Args:
            input_dir: A string pointing to the directory to import data from.
            output_dir: A string pointing to the directory to output data to.
            species_id: A list with the species IDs.

        Returns:
            None.

        """
        if not species_id:
            # default to just human
            species_id = ['9606']
        file_path = os.path.join(self.input_base_dir, 'gene_info.gz')

        with gzip.open(file_path, 'rt') as FH:
            for line in tqdm(FH, desc="Loading gene info"):
                records = line.split('\t')
                if records[0] not in species_id:
                    continue
                ncbi_gene_identifier = records[1]
                symbol = records[2]
                hgnc_identifier = self.get_identifier_by_prefix(records[5], 'HGNC:')
                description = records[8]
                if symbol not in self.gene_info_map:
                    self.gene_info_map[symbol] = {
                        'symbol': symbol,
                        'description': description,
                        'NCBI': ncbi_gene_identifier,
                        'HGNC': hgnc_identifier
                    }

    def load_country_code(self, input_dir: str, output_dir: str) -> None:
        file_path = os.path.join(input_dir, 'wikidata_country_codes.tsv')
        if os.path.exists(file_path):
            with open(file_path, 'r') as FH:
                for line in tqdm(FH, desc="Loading country codes"):
                    if line.startswith('item'):
                        continue
                    records = line.rstrip().split('\t')
                    self.country_code_map[records[1]] = (records[0], records[2])
        else:
            print(f"{file_path} not found. Failed to preload Wikidata country codes")

    @staticmethod
    def get_identifier_by_prefix(record, prefix):
        """Get identifier from a list based on prefix.

        Args:
            record: record from NCBI gene_info.
            prefix: prefix of the identifier to extract.

        Returns:
            str

        """
        identifier = None
        element = record.split('|')
        identifier = [x for x in element if prefix in x]
        if identifier:
            identifier = identifier[0]
            if 'HGNC:HGNC:' in identifier:
                identifier = ':'.join(identifier.split(':')[1:])
        return identifier








