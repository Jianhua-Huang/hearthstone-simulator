"""P09 packet survival, physical paid-body rewards and latest own intervals."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from dataclasses import asdict, replace
import json
import re
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_reactive_p09_cards import (
    EVENTUALITY, RIOTER, GOON, WILDSPEAKER, ROOTS, PREFIX, load_batch, register_simple_reactive_p09_cards,
)
from hs_sim.engine import (
    CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game, IllegalAction,
    Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone,
)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (
    AddToHand, ChangeControl, ChoiceOption, Damage, DamageBatch, Destroy, GainArmor,
    GainTemporaryMana, Heal, InvokeBehavior, Overload, RequestChoice, ReturnToHand, Silence, Transform,
)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.interrupts import CounterMinion
from hs_sim.engine.model import DamageKind
from hs_sim.engine.play_history import play_record
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.turn_scheduling import QueueTurns, SkipTurns
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

TEST='p09.test.'
YETI='CORE_CS2_182'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


def registry():
    r=build_registry();present=tuple(cid in r.cards for cid in ROOTS)
    if any(present)and not all(present):raise AssertionError('Partial P09 registration')
    if not all(present):register_simple_reactive_p09_cards(r)
    def summon(c,cid):return SummonByCard(c.player_id,(SummonEntryMaterial(cid),),SummonCause.capture(c))
    def reenter(c):return(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,cause=SummonCause.capture(c)),)
    def self_reenter(c):return(ReturnToHand(c.source_id),InvokeBehavior(TEST+'reenter',c.source_id,c.player_id,c.source_id))
    def wait(c,extra=()):
        return(RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',()),
            ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,c.player_id),)),*extra,
        ),c.source_id),)
    def health_wait(c):
        result=c.health_result
        if result is None or result.damage_dealt<=0 or result.target_card_id!=TEST+'plain':return ()
        source=next((i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==RIOTER),None)
        extra=()if source is None else(ChoiceOption('kill','Destroy accepted Rioter',(Destroy(source,c.source_id),)),)
        return wait(c,(
            ChoiceOption('bounce','Return and reenter old recipient',(ReturnToHand(result.target_id),InvokeBehavior(TEST+'reenter',c.source_id,c.player_id,result.target_id))),
            ChoiceOption('control','Give original recipient to opponent',(ChangeControl(result.target_id,2),)),
            ChoiceOption('transform','Transform original recipient',(Transform(result.target_id,TEST+'form'),)),*extra,
        ))
    def spell_wait(c):return wait(c)if c.health_result is not None and c.health_result.source_card_id==EVENTUALITY else ()
    def play_wait(c):
        row=play_record(c.state,dict(c.event.data)['play_id'])
        if row.card_id!=TEST+'battlecry' or row.player_id!=c.player_id:return ()
        return wait(c,(ChoiceOption('bounce','Return and reenter original played body',(
            ReturnToHand(row.source_id),InvokeBehavior(TEST+'reenter',c.source_id,c.player_id,row.source_id))),))
    def mana_wait(c):return wait(c)if c.event.player_id==c.player_id and dict(c.event.data).get('operation')=='RefreshMana'else ()
    def counter(c):
        return(CounterMinion(dict(c.event.data)['window_id']),)if c.event.player_id!=c.player_id and c.state.entities[c.event.source_id].kind==CardType.MINION else ()
    scripts={
        'hit':lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        'zero':lambda c:(Damage(c.target_id,0,c.source_id,DamageKind.SPELL),),
        'lethal':lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL),),
        'heal':lambda c:(Heal(c.target_id,2,c.source_id),),
        'double':lambda c:(DamageBatch((Damage(c.target_id,1,c.source_id),Damage(c.target_id,1,c.source_id))),),
        'double_lethal':lambda c:(DamageBatch((Damage(c.target_id,1,c.source_id),Damage(c.target_id,3,c.source_id))),),
        'kill_listener':lambda c:(DamageBatch((Damage(next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==RIOTER),6,c.source_id),Damage(c.target_id,1,c.source_id))),),
        'silence':lambda c:(Silence(c.target_id),),
        'summon':lambda c:(summon(c,TEST+'battlecry'),),
        'wound_enemy':lambda c:(Damage(c.state.players[2].hero_id,28,c.source_id),),
        'noop':lambda c:(),
        'extra':lambda c:(QueueTurns((1,1,2),c.source_id),),
        'skip_owner':lambda c:(SkipTurns(1,1,c.source_id),),
        'overload':lambda c:(Overload(c.player_id,2),),
        'temporary':lambda c:(GainTemporaryMana(c.player_id,2),),
    }
    for name,body in scripts.items():
        key=TEST+name;r.register_behavior(key,body)
        targeted=name in('hit','zero','lethal','heal','double','double_lethal','kill_listener','silence')
        r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=META,
            targeting=TargetSpec(zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION))if targeted else None))
    bc={
        'battlecry':lambda c:(GainArmor(c.player_id,1),),
        'die':lambda c:(Destroy(c.source_id,c.source_id),),
        'change':lambda c:(Transform(c.source_id,TEST+'plain'),),
        'self_silence':lambda c:(Silence(c.source_id),),
        'bounce':self_reenter,
        'poison_hit':lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.MINION_ABILITY),),
    }
    for name,body in bc.items():
        key=TEST+name;r.register_behavior(key,body)
        r.register_card(CardDefinition(key,name,CardType.MINION,attack=1,health=3,battlecry=key,metadata=META,
            keywords=(Keyword.POISONOUS,)if name=='poison_hit'else(),
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if name=='poison_hit'else None))
    for name,keywords in(('plain',()),('form',()),('shield',(Keyword.DIVINE_SHIELD,)),('immune',(Keyword.IMMUNE,))):
        r.register_card(CardDefinition(TEST+name,name,CardType.MINION,attack=1,health=3,keywords=keywords,metadata=META))
    r.register_card(CardDefinition(TEST+'bonus','Spell damage',CardType.MINION,health=6,spell_damage=2,metadata=META))
    r.register_behavior(TEST+'reenter',reenter);r.register_behavior(TEST+'fail',lambda c:(AddToHand(c.player_id,'p09.missing'),))
    for name,event,body in(('health_wait','health_resolved',health_wait),('spell_wait','health_resolved',spell_wait),
                            ('play_wait','card_played',play_wait),('mana_wait','mana_changed',mana_wait),('counter','card_committed',counter)):
        key=TEST+name;r.register_behavior(key,body)
        r.register_card(CardDefinition(key,name,CardType.MINION,health=9,metadata=META,triggers=(TriggerSpec(event,key),)))
    r.validate();return r


class SimpleReactiveP09CardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),*,hero='HERO_08',enemy_hand=(),active=1,mana=40,maximum=40,cap=40):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero,hand=hand,board=board,deck=(YETI,)*14,mana=mana,max_mana=maximum,mana_cap=cap),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*14,mana=40,max_mana=40,mana_cap=40),
        ),active_player=active,seed=909),self.r)
    def entities(self,g,cid,p=1,zone='board'):
        return[g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid]
    def first(self,g,cid,p=1,zone='board'):return self.entities(g,cid,p,zone)[0]
    def play(self,g,cid,target=None):
        p=g.state.active_player;eid=self.first(g,cid,p,'hand').id
        g.apply(PlayCard(p,eid,target,len(g.state.players[p].board)if self.r.card(cid).kind==CardType.MINION else None));return eid
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def cycle(self,g):self.end(g);self.end(g)
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','MinionReference','BoardPresenceReference','submitted_cost','played_face','owner_turn_history','behavior_id'):
                self.assertNotIn(key,public)
        return other

    def test_complete_raw_official_roots_and_existing_rogue_imbue_power(self):
        d=load_batch();self.assertEqual(tuple(x['record']['id']for x in d['cards']),ROOTS)
        self.assertEqual(len(d['official_observations']['observations']),10)
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['dependencies']);self.assertFalse(d['skipped'])
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']+d['existing_dependencies']:
            raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256'])
            for o in(o for o in d['official_observations']['observations']if o['card_id']==raw['id']):
                face=o['face'];en=o['locale']=='en-us';self.assertEqual(face['name'],raw['name_en'if en else'name'])
                self.assertEqual((face['id'],face['manaCost'],face['cardSetId'],face['cardTypeId']),(raw['dbf_id'],raw['cost'],raw['card_set_id'],raw['tags']['CARDTYPE']))
                if raw['id']in ROOTS:self.assertEqual(norm(face['text']),norm(raw['text_en'if en else'text']))
            if raw['id']in ROOTS:self.assertEqual(self.r.card(raw['id']).metadata,replace(metadata_from_record(raw),deck_identity=raw['id']))
        dep,=d['existing_dependencies'];self.assertEqual(canonical_digest(asdict(self.r.card('END_000p'))),dep['definition_sha256'])
        self.assertEqual(self.r.card(GOON).metadata.tribes,('elemental',));self.assertIn(Keyword.TAUNT,self.r.card(WILDSPEAKER).keywords)

    def test_default_311_and_fingerprint_unchanged(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311)
        self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_eventuality_actual_shadow_damage_then_rogue_imbue_and_single_payment(self):
        g=self.game((EVENTUALITY,),enemy=(YETI,),hero='HERO_03');self.play(g,EVENTUALITY,self.first(g,YETI,2).id)
        self.assertEqual(self.first(g,YETI,2).health,3);self.assertEqual(g.state.players[1].mana,38)
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,'END_000p')
        self.assertEqual(len(g.state.imbue_history),1);self.assertEqual(len(g.state.play_history),1)
        health=next(e.sequence for e in g.events if e.kind=='health_resolved');imbue=next(e.sequence for e in g.events if e.kind=='imbued')
        self.assertLess(health,imbue);self.portable(g)

    def test_eventuality_spell_damage_uses_original_spell_packet(self):
        g=self.game((EVENTUALITY,),(TEST+'bonus',),enemy=(YETI,),hero='HERO_03');self.play(g,EVENTUALITY,self.first(g,YETI,2).id)
        self.assertEqual(self.first(g,YETI,2).health,1);self.assertEqual(len(g.state.imbue_history),1)

    def test_eventuality_invalid_missing_target_rolls_back_before_payment(self):
        g=self.game((EVENTUALITY,),hero='HERO_03');saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,EVENTUALITY)
        self.assertEqual(g.snapshot(),saved)

    def test_eventuality_counter_suppresses_damage_and_imbue(self):
        g=self.game((EVENTUALITY,),enemy=(YETI,),hero='HERO_03',enemy_hand=('EX1_287',),active=2)
        self.play(g,'EX1_287');self.end(g);self.play(g,EVENTUALITY,self.first(g,YETI,2).id)
        self.assertEqual(self.first(g,YETI,2).health,5);self.assertFalse(g.state.imbue_history);self.assertTrue(g.state.play_history[-1].countered)

    def test_eventuality_damage_choice_restores_rolls_back_and_resumes_imbue_once(self):
        g=self.game((EVENTUALITY,),(TEST+'spell_wait',),enemy=(YETI,),hero='HERO_03');self.play(g,EVENTUALITY,self.first(g,YETI,2).id)
        self.assertFalse(g.state.imbue_history);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(len(g.state.imbue_history),1);self.assertEqual(g.state.players[1].mana,38)

    def test_eventuality_terminal_damage_stops_later_imbue(self):
        g=self.game((TEST+'wound_enemy',EVENTUALITY),hero='HERO_03');self.play(g,TEST+'wound_enemy');self.play(g,EVENTUALITY,self.hero(g,2).id)
        self.assertEqual(g.state.winner,1);self.assertFalse(g.state.imbue_history);self.portable(g)

    def test_rioter_rewards_original_friendly_survivor_and_itself(self):
        g=self.game((TEST+'hit',TEST+'hit'),(RIOTER,TEST+'plain'));target=self.first(g,TEST+'plain').id
        self.play(g,TEST+'hit',target);self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(2,2))
        source=self.first(g,RIOTER).id;self.play(g,TEST+'hit',source)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(2,5));self.portable(g)

    def test_rioter_ignores_heroes_opponents_zero_healing_shield_and_immunity(self):
        for name,cid,owner in(('hit','hero',1),('hit',TEST+'plain',2),('zero',TEST+'plain',1),
                             ('heal',TEST+'plain',1),('hit',TEST+'shield',1),('hit',TEST+'immune',1)):
            with self.subTest(name=name,card=cid,owner=owner):
                own=TEST+'plain'if cid=='hero'or owner==2 else cid
                g=self.game((TEST+name,),(RIOTER,own),enemy=(TEST+'plain',))
                target=self.hero(g).id if cid=='hero'else self.first(g,cid,owner).id
                self.play(g,TEST+name,target);self.assertEqual(self.first(g,own).attack,1)
                self.assertEqual(self.first(g,RIOTER).attack,1)

    def test_rioter_lethal_or_poison_is_not_a_survival_reward(self):
        for source in(TEST+'lethal',TEST+'poison_hit'):
            with self.subTest(source=source):
                g=self.game((source,),(RIOTER,TEST+'plain'));target=self.first(g,TEST+'plain').id;self.play(g,source,target)
                self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[target].attack,1)

    def test_rioter_two_original_surviving_packets_each_add_one_attack(self):
        g=self.game((TEST+'double',),(RIOTER,TEST+'plain'));target=self.first(g,TEST+'plain').id;self.play(g,TEST+'double',target)
        self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(3,1));self.portable(g)

    def test_rioter_later_lethal_packet_or_dead_listener_does_not_buff_dead_material(self):
        for cid in(TEST+'double_lethal',TEST+'kill_listener'):
            with self.subTest(card=cid):
                g=self.game((cid,),(RIOTER,TEST+'plain'));target=self.first(g,TEST+'plain').id;self.play(g,cid,target)
                self.assertEqual(g.state.entities[target].attack,1)

    def test_rioter_two_live_listeners_are_two_independent_rewards(self):
        g=self.game((TEST+'hit',),(RIOTER,RIOTER,TEST+'plain'));target=self.first(g,TEST+'plain').id;self.play(g,TEST+'hit',target)
        self.assertEqual(g.state.entities[target].attack,3)

    def test_rioter_damage_wait_restores_and_original_reference_skips_same_id_reentry(self):
        g=self.game((TEST+'hit',),(TEST+'health_wait',RIOTER,TEST+'plain'));target=self.first(g,TEST+'plain').id
        self.play(g,TEST+'hit',target);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'bounce');self.choose(other,'bounce');self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(1,3));self.portable(g)

    def test_rioter_original_reference_rejects_later_control_or_transform(self):
        for branch in('control','transform'):
            with self.subTest(branch=branch):
                g=self.game((TEST+'hit',),(TEST+'health_wait',RIOTER,TEST+'plain'));target=self.first(g,TEST+'plain').id
                self.play(g,TEST+'hit',target);self.choose(g,branch);self.assertEqual(g.state.entities[target].attack,1)

    def test_rioter_accepted_reward_survives_later_listener_death(self):
        g=self.game((TEST+'hit',),(TEST+'health_wait',RIOTER,TEST+'plain'));target=self.first(g,TEST+'plain').id
        self.play(g,TEST+'hit',target);self.choose(g,'kill');self.assertEqual(g.state.entities[target].attack,2)

    def test_goon_rewards_actual_battlecry_play_after_payload_once(self):
        g=self.game((TEST+'battlecry',),(GOON,));target=self.play(g,TEST+'battlecry')
        self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(2,4));self.assertEqual(self.hero(g).armor,1)
        self.portable(g)

    def test_goon_ordinary_minion_and_effect_summon_are_not_battlecry_plays(self):
        g=self.game((TEST+'plain',TEST+'summon'),(GOON,));plain=self.play(g,TEST+'plain');self.play(g,TEST+'summon')
        self.assertEqual(g.state.entities[plain].attack,1);self.assertEqual(self.first(g,TEST+'battlecry').attack,1);self.assertEqual(self.hero(g).armor,0)

    def test_goon_enemy_or_countered_battlecry_play_has_no_reward(self):
        g=self.game(board=(GOON,),enemy_hand=(TEST+'battlecry',),active=2);self.play(g,TEST+'battlecry')
        self.assertEqual(self.first(g,TEST+'battlecry',2).attack,1)
        g=self.game((TEST+'battlecry',),(GOON,),enemy=(TEST+'counter',));target=self.play(g,TEST+'battlecry')
        self.assertTrue(g.state.play_history[-1].countered);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual(self.hero(g).armor,0)

    def test_goon_original_submitted_battlecry_qualifies_after_same_residence_transform_or_silence(self):
        for cid in(TEST+'change',TEST+'self_silence'):
            with self.subTest(card=cid):
                g=self.game((cid,),(GOON,));target=self.play(g,cid)
                self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(2,4))

    def test_goon_dead_or_reentered_battlecry_body_never_receives_old_reward(self):
        for cid in(TEST+'die',TEST+'bounce'):
            with self.subTest(card=cid):
                g=self.game((cid,),(GOON,));target=self.play(g,cid)
                self.assertEqual(g.state.entities[target].attack,1)
                self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD if cid==TEST+'die'else Zone.BOARD)

    def test_goon_repeated_battlecry_still_rewards_completed_paid_play_only_once(self):
        g=self.game((TEST+'battlecry',),(GOON,'TIME_064'));target=self.play(g,TEST+'battlecry')
        self.assertEqual(self.hero(g).armor,2);self.assertEqual(g.state.entities[target].attack,2)
        self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_goon_earlier_completed_play_wait_cannot_rebind_original_recipient(self):
        g=self.game((TEST+'battlecry',),(TEST+'play_wait',GOON));target=self.play(g,TEST+'battlecry')
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'bounce');self.choose(other,'bounce');self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(g.state.entities[target].attack,1);self.portable(g)

    def test_goon_itself_has_no_battlecry_and_is_not_self_rewarded(self):
        g=self.game((GOON,));target=self.play(g,GOON);self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(2,3))

    def test_wildspeaker_first_interval_restores_three_spent_mana_without_crystals(self):
        g=self.game((WILDSPEAKER,),mana=10,maximum=10,cap=10);target=self.play(g,WILDSPEAKER)
        p=g.state.players[1];self.assertEqual((p.mana,p.max_mana,p.mana_cap),(8,10,10))
        self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(3,7));self.assertIn(Keyword.TAUNT,g.state.entities[target].keywords)
        self.portable(g)

    def test_wildspeaker_previous_own_minion_blocks_refresh_even_after_death(self):
        g=self.game((TEST+'die',WILDSPEAKER));self.play(g,TEST+'die');self.cycle(g);self.play(g,WILDSPEAKER)
        self.assertEqual(g.state.players[1].mana,35)

    def test_wildspeaker_only_previous_interval_matters_not_current_or_opponent_plays(self):
        g=self.game((TEST+'noop',TEST+'plain',WILDSPEAKER),enemy_hand=(TEST+'battlecry',))
        self.play(g,TEST+'noop');self.end(g);self.play(g,TEST+'battlecry');self.end(g)
        self.play(g,TEST+'plain');self.play(g,WILDSPEAKER);self.assertEqual(g.state.players[1].mana,38)

    def test_wildspeaker_prior_effect_summon_is_not_prior_minion_play(self):
        g=self.game((TEST+'summon',WILDSPEAKER));self.play(g,TEST+'summon');self.cycle(g);self.play(g,WILDSPEAKER)
        self.assertEqual(g.state.players[1].mana,38)

    def test_wildspeaker_previous_countered_minion_still_counts_as_committed_play(self):
        g=self.game((TEST+'plain',WILDSPEAKER),enemy=(TEST+'counter',));self.play(g,TEST+'plain');self.cycle(g)
        # The same counter would counter Wildspeaker too, so silence it first.
        # Use an already held zero-cost local silence to retain actual history.
        g=self.game((TEST+'plain',TEST+'silence',WILDSPEAKER),enemy=(TEST+'counter',))
        self.play(g,TEST+'plain');self.play(g,TEST+'silence',self.first(g,TEST+'counter',2).id);self.cycle(g);self.play(g,WILDSPEAKER)
        self.assertTrue(g.state.play_history[0].countered);self.assertEqual(g.state.players[1].mana,35)

    def test_wildspeaker_extra_empty_owner_interval_replaces_earlier_minion_turn(self):
        g=self.game((TEST+'plain',TEST+'extra',WILDSPEAKER));self.play(g,TEST+'plain');self.play(g,TEST+'extra');self.end(g);self.end(g)
        self.assertEqual(g.state.active_player,1);self.play(g,WILDSPEAKER);self.assertEqual(g.state.players[1].mana,38);self.portable(g)

    def test_wildspeaker_skipped_owner_slot_does_not_invent_empty_previous_interval(self):
        g=self.game((TEST+'plain',TEST+'skip_owner',WILDSPEAKER));self.play(g,TEST+'plain');self.play(g,TEST+'skip_owner');self.cycle(g)
        self.assertEqual(g.state.active_player,2);self.end(g);self.play(g,WILDSPEAKER)
        self.assertEqual(g.state.players[1].mana,35)

    def test_wildspeaker_refresh_preserves_overload_and_temporary_consumption_accounts(self):
        g=self.game((TEST+'overload',TEST+'temporary',WILDSPEAKER),mana=10,maximum=10,cap=10)
        self.play(g,TEST+'overload');self.cycle(g);self.play(g,TEST+'temporary');self.play(g,WILDSPEAKER)
        p=g.state.players[1];self.assertEqual((p.mana,p.max_mana,p.mana_cap,p.overload_locked,p.temporary_mana,p.mana_spent),(8,10,10,2,0,0));self.portable(g)

    def test_wildspeaker_refresh_observer_wait_restores_rolls_back_without_repaying(self):
        g=self.game((WILDSPEAKER,),(TEST+'mana_wait',));self.play(g,WILDSPEAKER)
        self.assertEqual(g.state.players[1].mana,38);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(g.state.players[1].mana,38);self.assertEqual(len(g.state.play_history),1)


if __name__=='__main__':unittest.main()
