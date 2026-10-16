"""A source export is explicitly versioned data, retaining unknowns and core sets."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from hs_sim.card_xml import read_card_xml
from hs_sim.catalog import CatalogError


ENTITY='''<Entity CardID="CORE_example" ID="100" version="2">
<Tag name="CARDNAME" type="LocString"><enUS>Example</enUS><zhCN>例子</zhCN></Tag>
<Tag name="CARDTEXT" type="LocString"><enUS>Unimplemented effect</enUS></Tag>
<Tag name="CARDTYPE" type="Int" value="4"/>
<Tag name="CARD_SET" type="Int" value="1810"/>
<Tag name="COLLECTIBLE" type="Int" value="1"/>
<Tag name="HERO_POWER" type="Card" value="101" cardID="power"/>
</Entity>'''


class CardXmlTests(unittest.TestCase):
    def read(self,contents,build=255026):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'CardDefs.xml';path.write_text(contents,encoding='utf-8')
            return read_card_xml(path,expected_build=build)

    def document(self,*entities):return '<CardDefs build="255026">'+''.join(entities)+'</CardDefs>'

    def test_retired_core_membership_and_absent_cost_stay_explicit(self):
        row=self.read(self.document(ENTITY)).cards[0]
        self.assertEqual((row['name'],row['name_en']),('例子','Example'))
        self.assertEqual(row['card_set_id'],1810)
        self.assertIsNone(row['cost'])
        self.assertEqual(row['text_en'],'Unimplemented effect')
        self.assertEqual(row['xml_card_references'],[{'tag':'HERO_POWER','dbf_id':101,'card_id':'power'}])
        self.assertEqual(row['related_dbf_ids'],[])

    def test_wrong_source_build_cannot_be_used_as_current_data(self):
        with self.assertRaises(CatalogError):self.read(self.document(ENTITY),build=255025)
        with self.assertRaises(CatalogError):self.read(self.document(ENTITY),build=True)

    def test_duplicate_card_or_dbf_identity_is_rejected(self):
        for extra in (ENTITY,ENTITY.replace('ID="100"','ID="200"').replace('CORE_example','core_EXAMPLE'),
                      ENTITY.replace('CORE_example','different')):
            with self.subTest(extra=extra),self.assertRaises(CatalogError):
                self.read(self.document(ENTITY,extra))

    def test_unknown_type_and_unmapped_nodes_are_retained(self):
        entity=ENTITY.replace('value="4"','value="900"').replace('</Entity>','<UnreviewedDependency id="x"/></Entity>')
        row=self.read(self.document(entity)).cards[0]
        self.assertEqual(row['type'],'UNMAPPED_CARDTYPE_900')
        self.assertEqual(row['unmapped_xml_nodes'],[{'tag':'UnreviewedDependency','attributes':{'id':'x'}}])

    def test_malformed_numeric_metadata_is_rejected(self):
        with self.assertRaises(CatalogError):self.read(self.document(ENTITY.replace('value="1810"','value="unknown"')))

    def test_unknown_numeric_tag_names_keep_distinct_enum_identities(self):
        entity=ENTITY.replace('</Entity>',
            '<Tag name="1" enumID="2165" type="Int" value="1"/>'
            '<Tag name="1" enumID="2542" type="Int" value="1"/></Entity>')
        row=self.read(self.document(entity)).cards[0]
        self.assertEqual((row['tags']['2165'],row['tags']['2542']),(1,1))
        self.assertEqual([n['normalized_key'] for n in row['unmapped_xml_nodes']],['2165','2542'])
