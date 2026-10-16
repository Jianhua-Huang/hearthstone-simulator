"""Real P08 hand/location/resource paths and original owner-end recipients."""
from dataclasses import asdict, replace
import json
import re
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_herald_p08_cards import (
    SHRINE, RITUAL, GATHERER, NOZDORMU, BREEZLING, WISP, ROOTS, PREFIX,
    load_batch, register_simple_herald_p08_cards,
)
from hs_sim.engine import (
    Attack, CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    IllegalAction, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice,
    TargetSpec, TriggerSpec, UseHeroPower, UseLocation, Zone,
)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (
    AddToHand, ChangeControl, ChoiceOption, Damage, Destroy, GrantKeyword,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform,
)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.herald import Herald
from hs_sim.engine.locations import RefreshLocation
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

TEST='p08.test.'
YETI='CORE_CS2_182'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


def registry():
    r=build_registry();present=tuple(cid in r.cards for cid in ROOTS)
    if any(present)and not all(present):raise AssertionError('Partial P08 registration')
    if not all(present):register_simple_herald_p08_cards(r)
    def summon(c,cid):return SummonByCard(c.player_id,(SummonEntryMaterial(cid),),SummonCause.capture(c))
    def wait(c,extra=()):
        return(RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',()),
            ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,c.player_id),)),*extra,
        ),c.source_id),)
    def herald_wait(c):return wait(c)if c.event.player_id==c.player_id else ()
    def hand_wait(c):
        e=c.state.entities[c.event.target_id]
        if c.event.player_id!=c.player_id or e.card_id not in(BREEZLING,WISP):return ()
        if e.card_id==BREEZLING and sum(c.state.entities[i].card_id==BREEZLING for i in c.state.players[c.player_id].hand)!=1:return ()
        source=next((i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==GATHERER),None)
        extra=()if source is None else(ChoiceOption('kill','Destroy original Gatherer',(Destroy(source,c.source_id),)),)
        return wait(c,extra)
    def fill(c):
        return(AddToHand(c.player_id,YETI,c.source_id),)if c.event.player_id==c.player_id and c.state.entities[c.event.source_id].card_id==GATHERER else ()
    def reenter(c):return(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,cause=SummonCause.capture(c)),)
    def noz_wait(c):
        e=c.state.entities[c.event.target_id]
        if e.card_id!=NOZDORMU or dict(c.event.data).get('ability_kind')!='keyword':return ()
        plain=next(c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==TEST+'plain')
        shield=next(c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==TEST+'shield')
        return wait(c,(
            ChoiceOption('bounce','Return and reenter same recipient',(
                ReturnToHand(plain.id),InvokeBehavior(TEST+'reenter',c.source_id,c.player_id,plain.id))),
            ChoiceOption('control','Give recipient to opponent',(ChangeControl(plain.id,2),)),
            ChoiceOption('transform','Transform original recipient',(Transform(plain.id,TEST+'new'),)),
            ChoiceOption('break','Break accepted Shield before its buff',(Damage(shield.id,1,c.source_id),)),
            ChoiceOption('grant','Give late Shield before accepted grant',(GrantKeyword(plain.id,Keyword.DIVINE_SHIELD,c.source_id),)),
            ChoiceOption('new','Summon after accepted inventory',(summon(c,TEST+'new'),)),
            ChoiceOption('kill','Destroy accepted Nozdormu source',(Destroy(e.id,c.source_id),)),
        ))
    scripts={
        'refresh':lambda c:(RefreshLocation(c.target_id,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'summon_gatherer':lambda c:(summon(c,GATHERER),),
        'auto_ritual':lambda c:(CastSpell(c.player_id,RITUAL,c.source_id),),
        'herald':lambda c:(Herald(c.player_id,c.source_id),),
    }
    for name,body in scripts.items():
        key=TEST+name;r.register_behavior(key,body)
        target=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.LOCATION,))if name=='refresh'else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if name in('silence','kill')else None
        r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=META,targeting=target))
    r.register_behavior(TEST+'reenter',reenter)
    r.register_behavior(TEST+'fail',lambda c:(AddToHand(c.player_id,'p08.missing'),))
    for name,keys,dormant in(('plain',(),False),('new',(),False),('shield',(Keyword.DIVINE_SHIELD,),False),('dormant',(),True)):
        r.register_card(CardDefinition(TEST+name,name,CardType.MINION,attack=1,health=3,metadata=META,
            keywords=keys,dormant_turns=3 if dormant else 0))
    for name,event,body in(('herald_wait','heralded',herald_wait),('hand_wait','card_added_to_hand',hand_wait),
                            ('fill','card_committed',fill),('noz_wait','ability_granted',noz_wait)):
        key=TEST+name;r.register_behavior(key,body)
        r.register_card(CardDefinition(key,name,CardType.MINION,health=9,metadata=META,triggers=(TriggerSpec(event,key),)))
    r.validate();return r


class SimpleHeraldP08CardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),*,hero='HERO_08',enemy_hand=(),active=1,deck=(YETI,)*14):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero,hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*14,mana=40,max_mana=40,mana_cap=40),
        ),active_player=active,seed=808),self.r)
    def entities(self,g,cid,p=1,zone='board'):
        return[g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid]
    def first(self,g,cid,p=1,zone='board'):return self.entities(g,cid,p,zone)[0]
    def play(self,g,cid,target=None):
        p=g.state.active_player;eid=self.first(g,cid,p,'hand').id
        g.apply(PlayCard(p,eid,target,len(g.state.players[p].board)if self.r.card(cid).kind in(CardType.MINION,CardType.LOCATION)else None));return eid
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def cycle(self,g):self.end(g);self.end(g)
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def use(self,g):g.apply(UseLocation(g.state.active_player,self.first(g,SHRINE).id))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','CardReference','MinionReference','behavior_id','end_turn_history'):
                self.assertNotIn(key,public)
        return other
    def waiting_noz(self):
        g=self.game(board=(NOZDORMU,TEST+'noz_wait',TEST+'plain',TEST+'shield'));self.end(g)
        self.assertIsNotNone(g.state.pending_choice);return g

    def test_complete_raw_official_root_faces_full_graph_and_existing_dependencies(self):
        d=load_batch();self.assertEqual(tuple(x['record']['id']for x in d['cards']),ROOTS)
        self.assertEqual(len(d['official_observations']['observations']),30)
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['skipped'])
        def normal(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']+d['dependencies']+d['existing_dependencies']+d['evidence_only']:
            raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256'])
            for o in(o for o in d['official_observations']['observations']if o['card_id']==raw['id']):
                face=o['face'];en=o['locale']=='en-us';self.assertEqual(face['name'],raw['name_en'if en else'name'])
                self.assertEqual((face['id'],face['cardTypeId'],face['cardSetId']),(raw['dbf_id'],raw['tags']['CARDTYPE'],raw['card_set_id']))
                if raw['id']in(*ROOTS,BREEZLING,WISP):
                    text=raw['text_en'if en else'text']
                    if raw['id']==SHRINE:text=text.replace('{0}',"Cho'gall"if en else'古加尔')
                    if raw['id']==RITUAL:text=text.replace('{0}',"Al'Akir"if en else'奥拉基尔')
                    self.assertEqual(normal(face['text']),normal(text))
                    self.assertEqual(face['manaCost'],0 if raw['id']==WISP else raw['cost'])
            if raw['id']in(*ROOTS,BREEZLING):self.assertEqual(self.r.card(raw['id']).metadata,replace(metadata_from_record(raw),deck_identity=raw['id']))
        for row in d['existing_dependencies']:self.assertEqual(canonical_digest(asdict(self.r.card(row['record']['id']))),row['definition_sha256'])
        self.assertEqual(self.r.card(GATHERER).metadata.classes,(CardClass.MAGE,))
        self.assertEqual(self.r.card(NOZDORMU).metadata.tribes,())
        self.assertEqual((self.r.card(BREEZLING).cost,self.r.card(BREEZLING).attack,self.r.card(BREEZLING).health),(1,1,1))
        self.assertIn(Keyword.RUSH,self.r.card(BREEZLING).keywords)
        self.assertEqual((self.r.card(WISP).cost,self.r.card(WISP).metadata.tribes),(0,('undead',)))

    def test_default_311_and_fingerprint_stay_unchanged(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311)
        self.assertEqual(r.fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')

    def test_shrine_play_is_four_mana_location_with_no_spell_or_immediate_body(self):
        g=self.game((SHRINE,),hero='HERO_07');source=self.play(g,SHRINE);e=g.state.entities[source]
        self.assertEqual((e.kind,e.durability,e.health,e.attack),(CardType.LOCATION,2,0,0))
        self.assertEqual(g.state.players[1].mana,36);self.assertFalse(g.state.herald_history)
        self.assertFalse(g.state.cast_history);self.assertEqual(len(g.state.players[1].deck),14)
        self.assertEqual(g.state.play_history[0].kind,CardType.LOCATION);self.portable(g)

    def test_shrine_actual_free_activation_heralds_then_draws(self):
        g=self.game((SHRINE,),hero='HERO_07');source=self.play(g,SHRINE);self.use(g)
        self.assertEqual(g.state.players[1].mana,36);self.assertEqual(len(g.state.herald_history),1)
        self.assertEqual(g.state.herald_history[0].source_id,source);self.assertEqual(g.state.herald_history[0].soldier_card_id,'CATA_725t')
        self.assertEqual((g.state.entities[source].durability,g.state.entities[source].location_cooldown),(1,2))
        self.assertEqual(len(g.state.players[1].deck),13)
        herald=next(e.sequence for e in g.events if e.kind=='heralded');draw=next(e.sequence for e in g.events if e.kind=='card_drawn')
        self.assertLess(herald,draw);self.portable(g)

    def test_shrine_cooldown_ticks_only_owner_starts_and_last_use_keeps_payload(self):
        g=self.game((SHRINE,),hero='HERO_07');source=self.play(g,SHRINE);self.use(g);saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.use(g)
        self.assertEqual(g.snapshot(),saved);self.end(g);self.assertEqual(g.state.entities[source].location_cooldown,2)
        self.end(g);self.assertEqual(g.state.entities[source].location_cooldown,1);self.cycle(g)
        self.assertEqual(g.state.entities[source].location_cooldown,0);before=len(g.state.players[1].deck);self.use(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.herald_history),2)
        self.assertEqual(len(g.state.players[1].deck),before-1);self.assertTrue(any(e.kind=='location_destroyed'for e in g.events));self.portable(g)

    def test_shrine_full_board_first_use_counts_without_soldier_last_use_releases_slot(self):
        g=self.game((TEST+'refresh',),(SHRINE,*(YETI,)*6),hero='HERO_07');source=self.first(g,SHRINE).id
        self.use(g);self.assertIsNone(g.state.herald_history[-1].soldier_id);self.assertEqual(len(g.state.players[1].deck),13)
        self.play(g,TEST+'refresh',source);self.use(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertIsNotNone(g.state.herald_history[-1].soldier_id)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(len(g.state.players[1].deck),12);self.portable(g)

    def test_shrine_herald_choice_restores_rolls_back_and_does_not_recharge_use(self):
        g=self.game(board=(SHRINE,TEST+'herald_wait'),hero='HERO_07');self.use(g)
        self.assertEqual(len(g.state.players[1].deck),14);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(len(g.state.herald_history),1);self.assertEqual(self.first(g,SHRINE).durability,1)
        self.assertEqual(len(g.state.players[1].deck),13)

    def test_shrine_draw_uses_existing_fatigue_without_reverting_herald(self):
        g=self.game(board=(SHRINE,),hero='HERO_07',deck=());self.use(g)
        self.assertEqual(len(g.state.herald_history),1);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,29)

    def test_ritual_heralds_then_gets_two_exact_rush_elementals_in_hand(self):
        g=self.game((RITUAL,),hero='HERO_02');source=self.play(g,RITUAL)
        self.assertEqual(g.state.players[1].mana,38);self.assertEqual(len(g.state.herald_history),1)
        self.assertEqual(g.state.herald_history[0].soldier_card_id,'CATA_565t')
        self.assertEqual(len(self.entities(g,BREEZLING,zone='hand')),2);self.assertFalse(self.entities(g,BREEZLING))
        self.assertEqual(len(g.state.players[1].board),1)
        events=[e for e in g.events if e.source_id==source]
        self.assertLess(next(e.sequence for e in events if e.kind=='heralded'),min(e.sequence for e in events if e.kind=='card_added_to_hand'))
        self.portable(g)

    def test_ritual_full_field_does_not_suppress_two_hand_cards(self):
        g=self.game((RITUAL,),(YETI,)*7,hero='HERO_02');self.play(g,RITUAL)
        self.assertIsNone(g.state.herald_history[-1].soldier_id);self.assertEqual(len(self.entities(g,BREEZLING,zone='hand')),2)

    def test_ritual_hand_overflow_uses_existing_created_burn_for_second_token(self):
        g=self.game((RITUAL,*(YETI,)*9),hero='HERO_02');self.play(g,RITUAL)
        self.assertEqual(len(self.entities(g,BREEZLING,zone='hand')),1)
        self.assertEqual(len(self.entities(g,BREEZLING,zone='graveyard')),1)
        self.assertEqual(sum(e.kind=='card_burned'for e in g.events),1);self.portable(g)

    def test_ritual_countered_payload_has_neither_herald_nor_tokens(self):
        g=self.game((RITUAL,),hero='HERO_02',enemy_hand=('EX1_287',),active=2)
        self.play(g,'EX1_287');self.end(g);self.play(g,RITUAL)
        self.assertTrue(g.state.play_history[-1].countered);self.assertFalse(g.state.herald_history)
        self.assertFalse(self.entities(g,BREEZLING,zone='hand'))

    def test_ritual_automatic_cast_does_not_invent_another_hand_play(self):
        g=self.game((TEST+'auto_ritual',),hero='HERO_02');self.play(g,TEST+'auto_ritual')
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(g.state.cast_history[-1].origin,'effect')
        self.assertEqual(len(g.state.herald_history),1);self.assertEqual(len(self.entities(g,BREEZLING,zone='hand')),2);self.portable(g)

    def test_ritual_two_actual_casts_pay_once_herald_twice_and_get_four_tokens(self):
        g=self.game((RITUAL,),('CATA_154',),hero='HERO_07');self.play(g,RITUAL)
        self.assertEqual(g.state.players[1].mana,38);self.assertEqual(len(g.state.play_history),1)
        self.assertEqual(len(g.state.cast_history),2);self.assertEqual(len(g.state.herald_history),2)
        self.assertEqual(len(self.entities(g,BREEZLING,zone='hand')),4);self.portable(g)

    def test_ritual_first_hand_add_wait_restores_remaining_second_add_once(self):
        g=self.game((RITUAL,),(TEST+'hand_wait',),hero='HERO_02');self.play(g,RITUAL)
        self.assertEqual(len(self.entities(g,BREEZLING,zone='hand')),1);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(len(self.entities(g,BREEZLING,zone='hand')),2)

    def test_generated_breezling_rush_uses_real_attack_legality(self):
        g=self.game((RITUAL,),enemy=(YETI,),hero='HERO_02');self.play(g,RITUAL);source=self.play(g,BREEZLING)
        enemy_hero=g.state.players[2].hero_id;target=self.first(g,YETI,2).id;saved=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(Attack(1,source,enemy_hero))
        self.assertEqual(g.snapshot(),saved);g.apply(Attack(1,source,target));self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)

    def test_gatherer_gets_official_undead_wisp_then_imbues_mage_power(self):
        g=self.game((GATHERER,));self.play(g,GATHERER)
        self.assertEqual(g.state.players[1].mana,38);self.assertEqual(len(self.entities(g,WISP,zone='hand')),1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,'EDR_851p')
        added=next(e.sequence for e in g.events if e.kind=='card_added_to_hand');imbued=next(e.sequence for e in g.events if e.kind=='imbued')
        self.assertLess(added,imbued);self.assertEqual(len(g.state.imbue_history),1);self.portable(g)

    def test_gatherer_summon_never_executes_battlecry(self):
        g=self.game((TEST+'summon_gatherer',));self.play(g,TEST+'summon_gatherer')
        self.assertEqual(len(self.entities(g,GATHERER)),1);self.assertFalse(g.state.imbue_history)
        self.assertFalse(self.entities(g,WISP,zone='hand'))

    def test_gatherer_second_play_preserves_current_power_entity_and_grows_history(self):
        g=self.game((GATHERER,GATHERER));self.play(g,GATHERER);power=g.state.players[1].hero_power_id;self.play(g,GATHERER)
        self.assertEqual(g.state.players[1].hero_power_id,power);self.assertEqual(len(g.state.imbue_history),2)
        self.assertEqual(len(self.entities(g,WISP,zone='hand')),2)

    def test_gatherer_full_hand_burn_still_imbues(self):
        g=self.game((GATHERER,*(YETI,)*9),(TEST+'fill',));self.play(g,GATHERER)
        self.assertFalse(self.entities(g,WISP,zone='hand'));self.assertEqual(len(self.entities(g,WISP,zone='graveyard')),1)
        self.assertEqual(len(g.state.imbue_history),1);self.portable(g)

    def test_gatherer_wisp_wait_restore_and_source_death_keeps_accepted_imbue(self):
        g=self.game((GATHERER,),(TEST+'hand_wait',));source=self.play(g,GATHERER)
        self.assertFalse(g.state.imbue_history);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'kill');self.choose(other,'kill');self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.imbue_history),1)

    def test_nozdormu_owner_end_accepts_shield_branch_and_excludes_dormant_location_enemy(self):
        g=self.game(board=(NOZDORMU,TEST+'plain',TEST+'shield',TEST+'dormant',SHRINE),enemy=(TEST+'plain',))
        self.end(g)
        for cid in(NOZDORMU,TEST+'plain'):self.assertIn(Keyword.DIVINE_SHIELD,self.first(g,cid).keywords)
        shield=self.first(g,TEST+'shield');self.assertEqual((shield.attack,shield.health),(4,6))
        self.assertIn(Keyword.DIVINE_SHIELD,shield.keywords);self.assertNotIn(Keyword.DIVINE_SHIELD,self.first(g,TEST+'dormant').keywords)
        self.assertFalse(self.first(g,SHRINE).keywords);self.assertNotIn(Keyword.DIVINE_SHIELD,self.first(g,TEST+'plain',2).keywords)
        self.assertTrue(g.state.end_turn_history[-1].completed);self.portable(g)

    def test_nozdormu_opponent_end_does_not_trigger_and_next_owner_end_buffs_existing_shield(self):
        g=self.game(board=(NOZDORMU,TEST+'plain'));self.end(g);self.end(g)
        self.assertEqual((self.first(g,NOZDORMU).attack,self.first(g,TEST+'plain').attack),(4,1))
        self.end(g);self.assertEqual((self.first(g,NOZDORMU).attack,self.first(g,TEST+'plain').attack),(7,4))

    def test_nozdormu_silence_removes_future_body(self):
        g=self.game((TEST+'silence',),(NOZDORMU,TEST+'plain'));self.play(g,TEST+'silence',self.first(g,NOZDORMU).id);self.end(g)
        self.assertNotIn(Keyword.DIVINE_SHIELD,self.first(g,TEST+'plain').keywords)

    def test_nozdormu_wait_restores_rolls_back_and_same_id_reentry_skips_original_grant(self):
        g=self.waiting_noz();source=self.first(g,TEST+'plain').id;presence=g.state.entities[source].board_presence_id
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'bounce');self.choose(other,'bounce');self.assertEqual(g.snapshot(),other.snapshot())
        entity=g.state.entities[source];self.assertNotEqual(entity.board_presence_id,presence)
        self.assertNotIn(Keyword.DIVINE_SHIELD,entity.keywords);self.assertEqual((entity.attack,entity.health),(1,3));self.portable(g)

    def test_nozdormu_original_reference_skips_transformed_or_transferred_recipient(self):
        for branch in('transform','control'):
            with self.subTest(branch=branch):
                g=self.waiting_noz();source=self.first(g,TEST+'plain').id;self.choose(g,branch)
                self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[source].keywords)
                self.assertEqual(g.state.entities[source].controller,2 if branch=='control'else 1)

    def test_nozdormu_late_shield_does_not_switch_accepted_grant_to_buff(self):
        g=self.waiting_noz();self.choose(g,'grant');e=self.first(g,TEST+'plain')
        self.assertIn(Keyword.DIVINE_SHIELD,e.keywords);self.assertEqual((e.attack,e.health),(1,3))

    def test_nozdormu_lost_shield_does_not_cancel_accepted_buff(self):
        g=self.waiting_noz();self.choose(g,'break');e=self.first(g,TEST+'shield')
        self.assertNotIn(Keyword.DIVINE_SHIELD,e.keywords);self.assertEqual((e.attack,e.health),(4,6))

    def test_nozdormu_new_summon_after_acceptance_does_not_join_original_inventory(self):
        g=self.waiting_noz();self.choose(g,'new');self.assertNotIn(Keyword.DIVINE_SHIELD,self.first(g,TEST+'new').keywords)

    def test_nozdormu_source_death_after_acceptance_keeps_other_recipient_effects(self):
        g=self.waiting_noz();source=self.first(g,NOZDORMU).id;self.choose(g,'kill')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertIn(Keyword.DIVINE_SHIELD,self.first(g,TEST+'plain').keywords)
        self.assertEqual(self.first(g,TEST+'shield').attack,4);self.portable(g)


if __name__=='__main__':unittest.main()
