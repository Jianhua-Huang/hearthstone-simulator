"""Native resources, finite persistent stages and three-reward public Auras."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from dataclasses import replace
import json
import re
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_temporal_p07_cards import (
    POWER, ACCELERATION, CHRONOLOGICAL, DRAKE, ROOTS, PREFIX, load_batch,
    register_simple_temporal_p07_cards,
)
from hs_sim.engine import (
    CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game, IllegalAction,
    Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone,
)
from hs_sim.engine.effects import (
    AddToHand, ChoiceOption, Destroy, InvokeBehavior, Overload, RequestChoice, SpendMana,
)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import SpellSchool
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.turn_scheduling import QueueTurns, SkipTurns
from hs_sim.targets import canonical_digest

TEST = 'p07.test.'
YETI = 'CORE_CS2_182'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


def registry():
    r=build_registry();present=tuple(cid in r.cards for cid in ROOTS)
    if any(present)and not all(present):raise AssertionError('Partial P07 registration')
    if not all(present):register_simple_temporal_p07_cards(r)
    def wait(c):
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok','Continue',()),
            ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,c.player_id),)),
        ),c.source_id),)
    def start_wait(c):return wait(c)if c.event.player_id==c.player_id else ()
    def mana_wait(c):
        return wait(c)if c.event.player_id==c.player_id and dict(c.event.data).get('operation')=='GainTemporaryMana'else ()
    def drake_wait(c):
        return wait(c)if c.event.player_id==c.player_id and c.state.entities[c.event.target_id].card_id==DRAKE else ()
    scripts={
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'capacity':lambda c:tuple(AddPlayerEffect(c.player_id,PREFIX+'acceleration',c.source_id)for _ in range(5)),
        'extra':lambda c:(QueueTurns((1,1,2),c.source_id),),
        'skip_owner':lambda c:(SkipTurns(1,1,c.source_id),),
        'overload':lambda c:(Overload(c.player_id,2),),
        'spend':lambda c:(SpendMana(c.player_id,1,c.source_id),),
    }
    for name,body in scripts.items():
        key=TEST+name;r.register_behavior(key,body)
        r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if name=='kill'else None))
    for name,cid in(('power',POWER),('acceleration',ACCELERATION),('chronological',CHRONOLOGICAL)):
        for enemy in(False,True):
            key=TEST+('enemy_'if enemy else'auto_')+name
            r.register_behavior(key,lambda c,cid=cid,enemy=enemy:(CastSpell(3-c.player_id if enemy else c.player_id,cid,c.source_id),))
            r.register_card(CardDefinition(key,name,CardType.MINION,health=3,battlecry=key,metadata=META))
    r.register_behavior(TEST+'fail',lambda c:(AddToHand(c.player_id,'p07.missing'),))
    for name,event,body in(('start_wait','turn_started',start_wait),('mana_wait','mana_changed',mana_wait),
                            ('drake_wait','minion_summoned',drake_wait)):
        key=TEST+name;r.register_behavior(key,body)
        r.register_card(CardDefinition(key,name,CardType.MINION,health=9,metadata=META,triggers=(TriggerSpec(event,key),)))
    r.validate();return r


class SimpleTemporalP07CardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),*,enemy_hand=(),active=1,mana=20,maximum=20,cap=40):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*15,mana=mana,max_mana=maximum,mana_cap=cap,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*15,mana=20,max_mana=20,mana_cap=40,hero_power_card_id='HERO_08bp'),
        ),active_player=active,seed=707),self.r)
    def entities(self,g,cid,p=1,zone='board'):
        return[g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid]
    def first(self,g,cid,p=1,zone='board'):return self.entities(g,cid,p,zone)[0]
    def play(self,g,cid,target=None):
        p=g.state.active_player;source=self.first(g,cid,p,'hand').id
        g.apply(PlayCard(p,source,target,len(g.state.players[p].board)if self.r.card(cid).kind==CardType.MINION else None));return source
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def cycle(self,g):self.end(g);self.end(g)
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def effects(self,g,p=1):return[x for x in g.state.players[p].player_effects if x.spec_id.startswith(PREFIX)]
    def resource_events(self,g,operation,p=1):
        return[e for e in g.events if e.kind=='mana_changed'and e.player_id==p and dict(e.data)['operation']==operation]
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','CardReference','MinionReference','owner_turn_history','behavior_id'):
                self.assertNotIn(key,public)
        return other

    def test_complete_pins_official_full_faces_three_turn_tags_and_exact_child(self):
        d=load_batch();self.assertEqual(tuple(x['record']['id']for x in d['cards']),ROOTS)
        self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['skipped'])
        self.assertEqual(len(d['official_observations']['observations']),8)
        def normalize(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_@]','',s)
        for row in d['cards']+d['dependencies']:
            raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256'])
            card=self.r.card(raw['id']);self.assertEqual(card.metadata,replace(metadata_from_record(raw),deck_identity=raw['id']))
            for o in(o for o in d['official_observations']['observations']if o['card_id']==raw['id']):
                face=o['face'];en=o['locale']=='en-us'
                self.assertEqual(face['name'],raw['name_en'if en else'name'])
                self.assertEqual(normalize(face['text']),normalize(raw['text_en'if en else'text']))
                for k,v in(('id',raw['dbf_id']),('manaCost',raw['cost']),('cardSetId',raw['card_set_id']),('cardTypeId',raw['tags']['CARDTYPE'])):self.assertEqual(face[k],v)
                if raw['id']==CHRONOLOGICAL:self.assertEqual(face['childIds'],[122736])
            if raw['id']in(ACCELERATION,CHRONOLOGICAL):
                self.assertEqual(tuple(raw['tags'][k]for k in('OBJECTIVE','PALADIN_AURA','TAG_SCRIPT_DATA_NUM_1','QUEST_PROGRESS_TOTAL')),(1,1,3,3))
        drake=self.r.card(DRAKE);self.assertEqual((drake.cost,drake.attack,drake.health),(4,3,5))
        self.assertEqual(drake.metadata.tribes,('dragon',));self.assertIn(Keyword.TAUNT,drake.keywords)
        self.assertEqual(self.r.card(POWER).spell_school,SpellSchool.SHADOW)
        self.assertEqual(self.r.card(ACCELERATION).spell_school,SpellSchool.HOLY)

    def test_default_311_definitions_and_fingerprint_unchanged(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311)
        self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_actual_paid_roots_charge_once_without_immediate_aura_rewards(self):
        for cid in ROOTS:
            with self.subTest(card=cid):
                g=self.game((cid,));source=self.play(g,cid);p=g.state.players[1]
                self.assertEqual((len(g.state.play_history),p.mana),(1,20-self.r.card(cid).cost))
                self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
                self.assertEqual(p.temporary_mana,0);self.assertFalse(self.entities(g,DRAKE))
                spec=self.r.player_effect(self.effects(g)[0].spec_id)
                self.assertEqual(spec.kind,'persistent'if cid==POWER else'aura')

    def test_power_destroys_ordinary_crystal_then_rewards_second_real_owner_start(self):
        g=self.game((POWER,),mana=10,maximum=10,cap=20);self.play(g,POWER)
        self.assertEqual((g.state.players[1].max_mana,g.state.players[1].mana),(9,8))
        self.cycle(g);self.assertEqual((g.state.players[1].max_mana,g.state.players[1].mana),(10,10))
        self.assertEqual(self.effects(g)[0].spec_id,PREFIX+'power_second');self.portable(g)
        self.cycle(g);self.assertEqual((g.state.players[1].max_mana,g.state.players[1].mana),(13,13))
        changes=self.resource_events(g,'ChangeManaCrystals')
        self.assertFalse(self.effects(g));self.assertEqual([e.amount for e in changes],[0,2])
        self.assertEqual([dict(e.data)['maximum']for e in changes],[9,13])
        self.cycle(g);self.assertEqual(len(self.resource_events(g,'ChangeManaCrystals')),2);self.portable(g)

    def test_power_zero_crystals_still_schedules_unconditional_later_gain(self):
        g=self.game((TEST+'auto_power',),mana=0,maximum=0,cap=20);self.play(g,TEST+'auto_power')
        self.assertEqual(g.state.players[1].max_mana,0);self.cycle(g);self.cycle(g)
        self.assertEqual((g.state.players[1].max_mana,g.state.players[1].mana),(4,4))
        self.assertFalse(self.effects(g));self.portable(g)

    def test_power_maximum_cap_clamps_reward_and_retires_stage(self):
        g=self.game((POWER,),mana=5,maximum=5,cap=5);self.play(g,POWER);self.cycle(g);self.cycle(g)
        self.assertEqual((g.state.players[1].max_mana,g.state.players[1].mana),(5,5))
        self.assertFalse(self.effects(g));self.assertEqual(self.resource_events(g,'ChangeManaCrystals')[-1].amount,0)

    def test_power_duplicates_advance_independent_native_stages(self):
        g=self.game((POWER,POWER));self.play(g,POWER);self.play(g,POWER)
        self.assertEqual(g.state.players[1].max_mana,18);self.assertEqual(len(self.effects(g)),2)
        self.cycle(g);self.assertTrue(all(e.spec_id==PREFIX+'power_second'for e in self.effects(g)))
        self.cycle(g);self.assertEqual(g.state.players[1].max_mana,24);self.assertFalse(self.effects(g));self.portable(g)

    def test_power_uses_no_objective_capacity_even_with_five_occupied_slots(self):
        g=self.game((TEST+'capacity',POWER));self.play(g,TEST+'capacity');self.play(g,POWER)
        self.assertEqual(len(self.effects(g)),6);self.cycle(g);self.assertEqual(len(self.effects(g)),6)
        self.cycle(g);self.assertEqual(len(self.effects(g)),5)
        self.assertFalse(any(e.spec_id.endswith('power_second')for e in self.effects(g)));self.portable(g)

    def test_power_offturn_cast_counts_recipient_starts_not_global_turns(self):
        g=self.game((TEST+'enemy_power',));self.play(g,TEST+'enemy_power')
        self.assertEqual(g.state.players[2].max_mana,19)
        self.end(g);self.assertEqual(g.state.players[2].max_mana,20)
        self.assertEqual(self.effects(g,2)[0].spec_id,PREFIX+'power_second')
        self.cycle(g);self.assertEqual(g.state.players[2].max_mana,23);self.assertFalse(self.effects(g,2));self.portable(g)

    def test_power_extra_owner_starts_complete_two_stages(self):
        g=self.game((POWER,TEST+'extra'));self.play(g,POWER);self.play(g,TEST+'extra')
        self.end(g);self.assertEqual(g.state.active_player,1);self.assertEqual(g.state.players[1].max_mana,20)
        self.end(g);self.assertEqual(g.state.active_player,1);self.assertEqual(g.state.players[1].max_mana,23)
        self.assertFalse(self.effects(g));self.portable(g)

    def test_power_skipped_owner_slot_never_advances_stage(self):
        g=self.game((POWER,TEST+'skip_owner'));self.play(g,POWER);self.play(g,TEST+'skip_owner');self.cycle(g)
        self.assertEqual(g.state.active_player,2);self.assertEqual(self.effects(g)[0].spec_id,PREFIX+'power_first')
        self.end(g);self.assertEqual(g.state.active_player,1);self.assertEqual(self.effects(g)[0].spec_id,PREFIX+'power_second')

    def test_power_actual_owner_start_wait_restores_rolls_back_and_never_double_advances(self):
        g=self.game((POWER,),(TEST+'start_wait',));self.play(g,POWER);self.cycle(g)
        self.assertEqual(self.effects(g)[0].spec_id,PREFIX+'power_first');other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(self.effects(g)[0].spec_id,PREFIX+'power_second')
        self.cycle(g);self.choose(g);self.assertFalse(self.effects(g));self.assertEqual(g.state.players[1].max_mana,23);self.portable(g)

    def test_auras_public_objectives_share_capacity_before_payment(self):
        g=self.game((ACCELERATION,)*5+(CHRONOLOGICAL,))
        for _ in range(5):self.play(g,ACCELERATION)
        for viewer in(1,2):
            row=next(p for p in g.for_player(viewer).observe()['observation']['players']if p['id']==1)
            self.assertEqual(len(row['player_effects']),5)
            self.assertTrue(all(e['effect_kind']=='aura'and e['remaining_turns']==3 for e in row['player_effects']))
        saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,CHRONOLOGICAL)
        self.assertEqual(g.snapshot(),saved);self.portable(g)

    def test_acceleration_three_future_owner_starts_including_last_before_expiry(self):
        g=self.game((ACCELERATION,));self.play(g,ACCELERATION)
        for remaining in(2,1,0):
            self.end(g);self.assertEqual(g.state.players[1].temporary_mana,0)
            self.assertEqual(g.state.players[2].temporary_mana,0)
            self.end(g);p=g.state.players[1];self.assertEqual((p.temporary_mana,p.mana),(1,p.max_mana+1))
            self.assertEqual(self.effects(g)[0].remaining_turns if self.effects(g)else 0,remaining)
        events=g.events;last=self.resource_events(g,'GainTemporaryMana')[-1]
        expiry=next(e for e in events if e.kind=='player_effect_expired'and dict(e.data).get('card_id')==ACCELERATION)
        self.assertLess(last.sequence,expiry.sequence);self.cycle(g)
        self.assertEqual(g.state.players[1].temporary_mana,0);self.assertEqual(len(self.resource_events(g,'GainTemporaryMana')),3);self.portable(g)

    def test_acceleration_temporary_account_exceeds_cap_without_permanent_growth(self):
        g=self.game((ACCELERATION,TEST+'spend'),mana=2,maximum=2,cap=2);self.play(g,ACCELERATION);self.cycle(g)
        p=g.state.players[1];self.assertEqual((p.max_mana,p.mana_cap,p.mana,p.temporary_mana),(2,2,3,1))
        self.play(g,TEST+'spend');p=g.state.players[1]
        self.assertEqual((p.mana,p.temporary_mana,p.mana_spent),(2,0,0))
        self.portable(g)

    def test_acceleration_refresh_precedes_bonus_and_existing_overload_stays_locked(self):
        g=self.game((ACCELERATION,TEST+'overload'),mana=5,maximum=5,cap=20)
        self.play(g,ACCELERATION);self.play(g,TEST+'overload');self.cycle(g)
        p=g.state.players[1];self.assertEqual((p.max_mana,p.overload_locked,p.temporary_mana,p.mana),(6,2,1,5))

    def test_acceleration_duplicate_instances_each_reward_and_count_down_once(self):
        g=self.game((ACCELERATION,ACCELERATION));self.play(g,ACCELERATION);self.play(g,ACCELERATION);self.cycle(g)
        self.assertEqual(g.state.players[1].temporary_mana,2);self.assertEqual([e.remaining_turns for e in self.effects(g)],[2,2])

    def test_acceleration_last_reward_wait_keeps_original_tick_and_resumes_once(self):
        g=self.game((ACCELERATION,),(TEST+'mana_wait',));self.play(g,ACCELERATION)
        for _ in range(2):self.cycle(g);self.choose(g)
        self.cycle(g);self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.effects(g)[0].remaining_turns,1)
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertFalse(self.effects(g));self.assertEqual(len(self.resource_events(g,'GainTemporaryMana')),3);self.portable(g)

    def test_chronological_three_real_owner_ends_including_cast_turn_then_no_fourth(self):
        g=self.game((CHRONOLOGICAL,));source=self.play(g,CHRONOLOGICAL)
        for total,remaining in((1,2),(2,1),(3,0)):
            self.end(g);self.assertEqual(len(self.entities(g,DRAKE)),total)
            self.assertEqual(self.effects(g)[0].remaining_turns if self.effects(g)else 0,remaining)
            self.end(g);self.assertEqual(len(self.entities(g,DRAKE)),total)
        self.assertTrue(all((e.attack,e.health)==(3,5)and Keyword.TAUNT in e.keywords for e in self.entities(g,DRAKE)))
        self.assertTrue(all(x.request.cause.source.entity_id==source for x in g.state.card_summon_history))
        self.cycle(g);self.assertEqual(len(self.entities(g,DRAKE)),3);self.portable(g)

    def test_chronological_full_board_still_ticks_expires_without_false_summon(self):
        g=self.game((CHRONOLOGICAL,),(YETI,)*7);self.play(g,CHRONOLOGICAL)
        for _ in range(3):self.cycle(g)
        self.assertFalse(self.effects(g));self.assertFalse(self.entities(g,DRAKE));self.assertFalse(g.state.successful_summon_history)
        self.portable(g)

    def test_chronological_original_shared_summon_quantity_doubles_only_actual_entries(self):
        g=self.game((CHRONOLOGICAL,),('CORE_DAL_575',));self.play(g,CHRONOLOGICAL);self.end(g)
        self.assertEqual(len(self.entities(g,DRAKE)),2);self.assertEqual(self.effects(g)[0].remaining_turns,2)
        self.portable(g)

    def test_chronological_last_end_reward_wait_restores_and_expires_after_payload(self):
        g=self.game((CHRONOLOGICAL,),(TEST+'drake_wait',));self.play(g,CHRONOLOGICAL)
        for _ in range(2):self.end(g);self.choose(g);self.end(g)
        self.end(g);self.assertEqual(self.effects(g)[0].remaining_turns,1);self.assertEqual(len(self.entities(g,DRAKE)),3)
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertFalse(self.effects(g));self.portable(g)

    def test_both_auras_extra_owner_turns_use_actual_boundaries(self):
        g=self.game((ACCELERATION,CHRONOLOGICAL,TEST+'extra'));self.play(g,ACCELERATION);self.play(g,CHRONOLOGICAL);self.play(g,TEST+'extra')
        for total in(1,2):
            self.end(g);self.assertEqual(g.state.active_player,1)
            self.assertEqual(len(self.entities(g,DRAKE)),total);self.assertEqual(g.state.players[1].temporary_mana,1)
        self.assertEqual([e.remaining_turns for e in self.effects(g)],[1,1]);self.portable(g)

    def test_both_auras_skipped_owner_slot_does_not_reward_or_tick(self):
        g=self.game((ACCELERATION,CHRONOLOGICAL,TEST+'skip_owner'));self.play(g,ACCELERATION);self.play(g,CHRONOLOGICAL)
        self.play(g,TEST+'skip_owner');self.cycle(g);self.assertEqual(g.state.active_player,2)
        self.assertEqual([e.remaining_turns for e in self.effects(g)],[3,2]);self.assertEqual(len(self.entities(g,DRAKE)),1)
        self.assertFalse(self.resource_events(g,'GainTemporaryMana'));self.end(g)
        self.assertEqual(self.effects(g)[0].remaining_turns,2);self.assertEqual(g.state.players[1].temporary_mana,1)

    def test_offturn_automatic_auras_use_original_recipient_boundaries(self):
        g=self.game((TEST+'enemy_acceleration',TEST+'enemy_chronological'))
        self.play(g,TEST+'enemy_acceleration');self.play(g,TEST+'enemy_chronological');self.end(g)
        self.assertEqual(g.state.players[2].temporary_mana,1);self.assertFalse(self.entities(g,DRAKE,2))
        self.assertEqual([e.remaining_turns for e in self.effects(g,2)],[2,3]);self.end(g)
        self.assertEqual(len(self.entities(g,DRAKE,2)),1);self.portable(g)

    def test_original_caster_departure_cancels_none_of_three_source_independent_rewards(self):
        for name,cid in(('power',POWER),('acceleration',ACCELERATION),('chronological',CHRONOLOGICAL)):
            with self.subTest(card=cid):
                g=self.game((TEST+'auto_'+name,TEST+'kill'));source=self.play(g,TEST+'auto_'+name)
                self.play(g,TEST+'kill',source);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
                self.cycle(g)
                if cid==POWER:self.cycle(g);self.assertFalse(self.effects(g));self.assertEqual(g.state.players[1].max_mana,23)
                elif cid==ACCELERATION:self.assertEqual(g.state.players[1].temporary_mana,1)
                else:self.assertEqual(len(self.entities(g,DRAKE)),1)

    def test_countered_roots_never_destroy_crystals_install_stages_or_objectives(self):
        for cid in ROOTS:
            with self.subTest(card=cid):
                g=self.game((cid,),enemy_hand=('EX1_287',),active=2);self.play(g,'EX1_287');self.end(g)
                maximum=g.state.players[1].max_mana;self.play(g,cid)
                self.assertTrue(g.state.play_history[-1].countered);self.assertEqual(g.state.players[1].max_mana,maximum)
                self.assertFalse(self.effects(g));self.assertFalse(self.entities(g,DRAKE))


if __name__=='__main__':unittest.main()
