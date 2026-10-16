"""Dream is a real printed class and never an additional playable hero seat."""
from copy import deepcopy
from dataclasses import replace
import json,unittest
from pathlib import Path
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (CardClass,CardDefinition,CardType,DeckSpec,Game,PlayCard,PlayerSetup,
    Scenario,SelectChoice,SnapshotError,SpellRepeatSpec)
from hs_sim.engine.class_tags import classes_from_tags
from hs_sim.engine.effects import ChoiceOption,GainArmor,RequestChoice
from hs_sim.engine.excavate import ExcavationClass,PLAYABLE_CLASSES as EXCAVATE_CLASSES
from hs_sim.engine.imbue import ImbueClass,PLAYABLE_CLASSES as IMBUE_CLASSES
from hs_sim.engine.model import PLAYABLE_CARD_CLASSES
from hs_sim.engine.pools import PoolQuery,matches_metadata
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import TargetValidationError,canonical_digest

DATA=Path(__file__).resolve().parents[1]/'data/support/dream-class-metadata.json'
PIN='42c0e7e5c9370644c15f91584ca91261c1003328fdd1338ec39b573b3e870cee'


def registry(wait=False):
    r=build_registry()
    r.register_behavior('dream.test.body',lambda c:(GainArmor(c.player_id,1),*(
        (RequestChoice(c.player_id,(ChoiceOption('ok','Continue',()),),c.source_id),)if wait else())))
    meta=metadata_from_record(dict(id='dream.test',type='SPELL',collectible=False,tags={'CLASS':11}))
    r.register_card(CardDefinition('dream.test','Dream class fixture',CardType.SPELL,cost=1,on_play='dream.test.body',metadata=meta))
    r.register_card(CardDefinition('dream.repeat','Other class repeat',CardType.MINION,health=5,spell_repeats=(SpellRepeatSpec(2),)))
    r.register_card(CardDefinition('dream.hero','Invalid playable Dream hero',CardType.HERO,health=30,metadata=meta))
    return r


class DreamClassMetadataTests(unittest.TestCase):
    def game(self,wait=False):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=('dream.test',),board=('dream.repeat',),mana=10,max_mana=10),PlayerSetup('HERO_08'))),registry(wait))
    def play(self,g):g.apply(PlayCard(1,g.state.players[1].hand[0]))
    def reject(self,s,r):
        s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError)as raised:Game.from_snapshot(s,r)
        self.assertNotIn('digest mismatch',str(raised.exception))

    def test_class11_and_its_single_mask_decode_as_dream_without_mutating_input(self):
        for tags in ({'CLASS':11},{'CLASS':11,'MULTIPLE_CLASSES':0},{'MULTIPLE_CLASSES':1<<10}):
            old=dict(tags);self.assertEqual(classes_from_tags(tags),(CardClass.DREAM,));self.assertEqual(tags,old)
        self.assertNotEqual(CardClass.DREAM,CardClass.NEUTRAL)

    def test_all_five_complete_real_dream_rows_preserve_exact_nonhero_class_metadata(self):
        data=json.loads(DATA.read_text(encoding='utf-8'));self.assertEqual(canonical_digest(data),PIN)
        rows=data['complete_rows'];found=[];self.assertEqual(len(data['official_observations']),10)
        for row in rows:
            raw=row['record']
            if raw['id']not in ('DREAM_01','DREAM_02','DREAM_03','DREAM_04','DREAM_05'):continue
            self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(raw['tags']['CLASS'],11)
            meta=metadata_from_record(raw);self.assertEqual(meta.classes,(CardClass.DREAM,));self.assertFalse(meta.collectible)
            if raw['id']=='DREAM_03':self.assertEqual(meta.tribes,('dragon',))
            found.append(raw['id'])
        self.assertEqual(len(found),5)

    def test_unknown_nonplayable_class13_bool_and_mask_bits_still_fail(self):
        for tags in ({'CLASS':13},{'CLASS':True},{'CLASS':4.0},{'MULTIPLE_CLASSES':1<<12},{'MULTIPLE_CLASSES':True}):
            with self.assertRaises(TargetValidationError):classes_from_tags(tags)

    def test_playable_hero_resource_sets_keep_original_eleven_classes(self):
        self.assertEqual(len(PLAYABLE_CARD_CLASSES),11);self.assertNotIn(CardClass.DREAM,PLAYABLE_CARD_CLASSES)
        self.assertNotIn(CardClass.NEUTRAL,PLAYABLE_CARD_CLASSES);self.assertEqual(EXCAVATE_CLASSES,PLAYABLE_CARD_CLASSES);self.assertEqual(IMBUE_CLASSES,PLAYABLE_CARD_CLASSES)

    def test_dream_is_rejected_as_deck_class_and_resource_profile_class(self):
        with self.assertRaises(ValueError):DeckSpec('HERO_08','HERO_08bp',CardClass.DREAM,())
        with self.assertRaises(ValueError):ImbueClass(CardClass.DREAM,None)
        with self.assertRaises(ValueError):ExcavationClass(CardClass.DREAM)

    def test_actual_dream_hero_scenario_cannot_create_an_extra_player_class(self):
        with self.assertRaises(ValueError):Game.from_scenario(Scenario((PlayerSetup('dream.hero'),PlayerSetup('HERO_08'))),registry())

    def test_rehashed_dream_current_and_starting_player_classes_are_rejected(self):
        g=self.game()
        for key in ('hero_class','deck_class'):
            s=g.snapshot();s['state']['players']['1'][key]='dream';self.reject(s,g.registry)

    def test_printed_dream_is_known_other_class_and_not_neutral_or_mage(self):
        meta=metadata_from_record(dict(id='dream.test',type='SPELL',collectible=False,tags={'CLASS':11}))
        def match(query):return matches_metadata(query,card_id='dream.test',kind=CardType.SPELL,cost=0,meta=meta,spell_school=None,keywords=(),current_class=CardClass.MAGE)
        self.assertTrue(match(PoolQuery(class_mode='other',include_neutral=False)))
        self.assertFalse(match(PoolQuery(class_mode='current',include_neutral=False)))
        self.assertTrue(match(PoolQuery(class_mode='specified',classes=(CardClass.DREAM,),include_neutral=False)))

    def test_real_other_class_repeat_quotes_pays_and_executes_dream_spell_twice(self):
        g=self.game();self.play(g);self.assertEqual(g.state.players[1].mana,9)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.assertEqual([x.origin for x in g.state.cast_history],['hand','repeat'])
        self.assertEqual(g.state.play_history[0].played_face.metadata.classes,(CardClass.DREAM,))
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),g.snapshot())

    def test_waiting_restore_clone_and_replay_keep_dream_metadata(self):
        g=self.game(True);self.play(g);s=g.snapshot();other=Game.from_snapshot(s,registry(True));self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry(True)).snapshot(),s)
        for current in (g,other):
            while current.state.pending_choice:
                q=current.state.pending_choice;current.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2)

    def test_default_representative_fingerprint_is_unchanged(self):
        from hs_sim.engine.representative import build_registry as defaults
        r=defaults();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')


if __name__=='__main__':unittest.main()
