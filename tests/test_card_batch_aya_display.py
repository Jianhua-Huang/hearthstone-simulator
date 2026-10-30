"""Aya's exact complete paired rule text permits only its declared live label."""
from copy import deepcopy
import unittest
from hs_sim.cards import past_stat_tribe_jade as native
from tools.card_batch import check_face


class AyaDisplayTests(unittest.TestCase):
    def source(self):
        d=native.load_batch()
        return next(x['record'] for x in d['cards'] if x['record']['id']==native.AYA),[
            x for x in d['official_observations'] if x['card_id']==native.AYA]
    def declaration(self,locale):return {'{0}':''} if locale=='zh_CN' else {}

    def test_complete_paired_faces_validate_without_mutating_evidence(self):
        raw,faces=self.source();saved=deepcopy((raw,faces));self.assertEqual(len(faces),2)
        for x in faces:check_face(raw,x['face'],x['locale'],self.declaration(x['locale']))
        self.assertEqual((raw,faces),saved)

    def test_missing_Chinese_declaration_is_rejected(self):
        raw,faces=self.source();face=next(x['face'] for x in faces if x['locale']=='zh_CN')
        with self.assertRaises(ValueError):check_face(raw,face,'zh_CN')

    def test_other_full_row_identity_or_stats_cannot_borrow_display(self):
        raw,faces=self.source()
        for key,value in (('id','CFM_691'),('attack',7),('health',4),('cost',5),('name','Other')):
            changed=dict(raw,**{key:value})
            for x in faces:
                with self.subTest(key=key,locale=x['locale']),self.assertRaises(ValueError):
                    check_face(changed,x['face'],x['locale'],self.declaration(x['locale']))

    def test_both_original_bodies_and_real_tags_are_required(self):
        raw,faces=self.source()
        for field in ('text','text_en'):
            for value in ('',raw[field]+' Draw a card.'):
                changed=dict(raw,**{field:value})
                for x in faces:
                    with self.assertRaises(ValueError):check_face(changed,x['face'],x['locale'],self.declaration(x['locale']))
        for tag in ('JADE_GOLEM','BATTLECRY','DEATHRATTLE'):
            changed=deepcopy(raw);changed['tags'][tag]=0
            for x in faces:
                with self.assertRaises(ValueError):check_face(changed,x['face'],x['locale'],self.declaration(x['locale']))

    def test_primary_cannot_lose_trigger_or_gain_additional_effect(self):
        raw,faces=self.source()
        for x in faces:
            face=x['face']
            for body in (face['text']+' Draw a card.',face['text'].replace('Deathrattle','Inspire').replace('亡语','激励')):
                with self.assertRaises(ValueError):check_face(raw,dict(face,text=body),x['locale'],self.declaration(x['locale']))

    def test_only_exact_empty_live_label_declaration_is_accepted(self):
        raw,faces=self.source()
        for x in faces:
            for extra in ({'{0}':'1/1'},{'{0}':'0'},{'@':''},{'{0}':'','@':''},{'{0}':'','{1}':''}):
                with self.assertRaises(ValueError):check_face(raw,x['face'],x['locale'],extra)

    def test_primary_identity_numbers_and_collectibility_remain_strict(self):
        raw,faces=self.source()
        for x in faces:
            for key,value in (('id',1),('attack',7),('health',4),('manaCost',5),('collectible',False),('cardTypeId',5)):
                with self.assertRaises(ValueError):
                    check_face(raw,dict(x['face'],**{key:value}),x['locale'],self.declaration(x['locale']))
