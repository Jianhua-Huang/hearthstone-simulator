"""P10 original Combo grants, current Demon branch and current Beast hand buff."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from dataclasses import replace
import json
from random import Random
import re
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_conditional_p10_cards import (
    ABERRATION,CONFINEMENT,NATURE,BLAZER,ROOTS,PREFIX,load_batch,register_simple_conditional_p10_cards,
)
from hs_sim.engine import (
    Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,IllegalAction,Keyword,
    PlayCard,PlayerSetup,Scenario,SelectChoice,TargetSpec,TriggerSpec,Zone,
)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (
    AddToHand,ChangeControl,ChoiceOption,Destroy,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Transform,
)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.interrupts import CounterMinion
from hs_sim.engine.model import TribeChangeSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.turn_scheduling import QueueTurns,SkipTurns
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

TEST='p10.test.';YETI='CORE_CS2_182';META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


def registry():
    r=build_registry();present=tuple(cid in r.cards for cid in ROOTS)
    if any(present)and not all(present):raise AssertionError('Partial P10 registration')
    if not all(present):register_simple_conditional_p10_cards(r)
    def summon(c,cid):return SummonByCard(c.player_id,(SummonEntryMaterial(cid),),SummonCause.capture(c))
    def reenter(c):return(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,cause=SummonCause.capture(c)),)
    def wait(c,extra=()):return(RequestChoice(c.player_id,(
        ChoiceOption('ok','Continue',()),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,c.player_id),)),*extra,
    ),c.source_id),)
    def change(c,operation,tribes):
        e=c.state.entities[c.target_id];ref=MinionReference.capture(e)if e.zone==Zone.BOARD else CardReference.capture(e)
        return(ChangeMinionTribes(ref,TribeChangeSpec(operation,tribes),c.source_id),)
    def overload_wait(c):
        if c.event.player_id!=c.player_id:return ()
        source=next((c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==ABERRATION),None)
        if source is None:return ()
        return wait(c,(
            ChoiceOption('bounce','Return and reenter same original source',(ReturnToHand(source.id),InvokeBehavior(TEST+'reenter',c.source_id,c.player_id,source.id))),
            ChoiceOption('kill','Destroy original source',(Destroy(source.id,c.source_id),)),
            ChoiceOption('control','Give original source to opponent',(ChangeControl(source.id,2),)),
        ))
    def board_wait(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id!=NATURE:return ()
        plain=next((c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==TEST+'plain'),None)
        beast=next((c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==TEST+'beast'),None)
        extra=()if plain is None or beast is None else(ChoiceOption('shift','Change actual hand Beast candidates',(
            ChangeMinionTribes(CardReference.capture(plain),TribeChangeSpec('set',('beast',)),c.source_id),
            ChangeMinionTribes(CardReference.capture(beast),TribeChangeSpec('set',('dragon',)),c.source_id),)),)
        return wait(c,extra)
    def hand_wait(c):
        source=c.state.entities.get(c.event.source_id)
        return wait(c)if source is not None and source.card_id==NATURE else ()
    def counter(c):return(CounterMinion(dict(c.event.data)['window_id']),)if c.event.player_id!=c.player_id and c.state.entities[c.event.source_id].kind==CardType.MINION else ()
    scripts={
        'noop':lambda c:(),
        'summon':lambda c:(summon(c,ABERRATION),),
        'beastify':lambda c:change(c,'set',('beast',)),
        'demonify':lambda c:change(c,'set',('demon',)),
        'unbeast':lambda c:change(c,'remove',('beast',)),
        'undemon':lambda c:change(c,'remove',('demon',)),
        'silence':lambda c:(Silence(c.target_id),),
        'extra_enemy':lambda c:(QueueTurns((2,2,1),c.source_id),),
        'skip_enemy':lambda c:(SkipTurns(2,1,c.source_id),),
    }
    for name,body in scripts.items():
        key=TEST+name;r.register_behavior(key,body)
        target=TargetSpec(zones=(Zone.HAND,Zone.BOARD),kinds=(CardType.MINION,),relation='friendly')if name in('beastify','demonify','unbeast','undemon')else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if name=='silence'else None
        r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=META,targeting=target))
    for name,tribes in(('plain',()),('beast',('beast',)),('demon',('demon',)),('all',('all',)),('unknown',None)):
        r.register_card(CardDefinition(TEST+name,name,CardType.MINION,cost=1,attack=1,health=3,metadata=replace(META,tribes=tribes)))
    r.register_behavior(TEST+'reenter',reenter);r.register_behavior(TEST+'fail',lambda c:(AddToHand(c.player_id,'p10.missing'),))
    for name,event,body in(('overload_wait','overload_added',overload_wait),('board_wait','stats_changed',board_wait),
                            ('hand_wait','stored_card_buffed',hand_wait),('counter','card_committed',counter)):
        key=TEST+name;r.register_behavior(key,body)
        r.register_card(CardDefinition(key,name,CardType.MINION,health=9,metadata=META,triggers=(TriggerSpec(event,key),)))
    r.validate();return r


class SimpleConditionalP10CardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),*,enemy_hand=(),active=1):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*14,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*14,mana=40,max_mana=40,mana_cap=40),
        ),active_player=active,seed=1010),self.r)
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
    def combo(self,g):self.play(g,TEST+'noop');return self.play(g,ABERRATION)
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','MinionReference','CardReference','submitted_cost','played_face','behavior_id'):
                self.assertNotIn(key,public)
        return other

    def test_full_raw_official_faces_metadata_and_no_invented_confinement_school(self):
        d=load_batch();self.assertEqual(tuple(x['record']['id']for x in d['cards']),ROOTS)
        self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['dependencies'])
        self.assertEqual(len(d['official_observations']['observations']),8)
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']+d['skipped']:
            raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256'])
            for o in(o for o in d['official_observations']['observations']if o['card_id']==raw['id']):
                face=o['face'];en=o['locale']=='en-us';self.assertEqual(face['name'],raw['name_en'if en else'name'])
                self.assertEqual(norm(face['text']),norm(raw['text_en'if en else'text']))
                self.assertEqual((face['id'],face['manaCost'],face['cardSetId'],face['cardTypeId']),(raw['dbf_id'],raw['cost'],raw['card_set_id'],raw['tags']['CARDTYPE']))
            if raw['id']in ROOTS:self.assertEqual(self.r.card(raw['id']).metadata,replace(metadata_from_record(raw),deck_identity=raw['id']))
        self.assertIsNone(self.r.card(CONFINEMENT).spell_school)
        self.assertEqual(self.r.card(ABERRATION).metadata.tribes,('dragon',))

    def test_blazer_complete_skip_is_explicit_without_partial_adapter_in_batch(self):
        row,=load_batch()['skipped'];self.assertEqual(row['record']['id'],BLAZER)
        self.assertNotIn(BLAZER,ROOTS);self.assertIn('unsupported_rule',row['reason'])

    def test_default_311_and_fingerprint_unchanged(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311)
        self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_aberration_without_combo_is_only_printed_rush(self):
        g=self.game((ABERRATION,));source=self.play(g,ABERRATION);e=g.state.entities[source]
        self.assertEqual((e.attack,e.health,g.state.players[1].mana,g.state.players[1].overload_owed),(4,4,36,0))
        self.assertIn(Keyword.RUSH,e.keywords);self.assertNotIn(Keyword.IMMUNE,e.keywords);self.assertNotIn(Keyword.WINDFURY,e.keywords)
        self.assertFalse(g.state.combo_history)

    def test_aberration_combo_overloads_once_then_expiring_immune_and_permanent_windfury(self):
        g=self.game((TEST+'noop',ABERRATION));source=self.combo(g);e=g.state.entities[source]
        self.assertIn(Keyword.IMMUNE,e.keywords);self.assertIn(Keyword.WINDFURY,e.keywords)
        self.assertEqual((g.state.players[1].mana,g.state.players[1].overload_owed,g.state.players[1].overload_locked),(36,2,0))
        self.assertEqual(len(g.state.combo_history),1);self.assertEqual(len(g.state.play_history),2);self.portable(g)
        self.end(g);self.assertNotIn(Keyword.IMMUNE,g.state.entities[source].keywords);self.assertIn(Keyword.WINDFURY,g.state.entities[source].keywords)
        self.end(g);p=g.state.players[1];self.assertEqual((p.mana,p.overload_locked,p.overload_owed),(38,2,0));self.portable(g)

    def test_aberration_rush_windfury_two_minion_attacks_with_real_immunity(self):
        g=self.game((TEST+'noop',ABERRATION),enemy=(YETI,YETI));source=self.combo(g);saved=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(Attack(1,source,g.state.players[2].hero_id))
        self.assertEqual(g.snapshot(),saved)
        for target in g.state.players[2].board:g.apply(Attack(1,source,target))
        self.assertEqual(g.state.entities[source].health,4);self.assertEqual(g.state.entities[source].attacks_this_turn,2)
        with self.assertRaises(IllegalAction):g.apply(Attack(1,source,g.state.players[2].board[0]))

    def test_aberration_effect_summon_has_rush_without_combo_or_overload(self):
        g=self.game((TEST+'summon',));self.play(g,TEST+'summon');e=self.first(g,ABERRATION)
        self.assertIn(Keyword.RUSH,e.keywords);self.assertNotIn(Keyword.WINDFURY,e.keywords);self.assertEqual(g.state.players[1].overload_owed,0)

    def test_aberration_overload_wait_restores_rolls_back_and_same_id_reentry_skips_old_grants(self):
        g=self.game((TEST+'noop',ABERRATION),(TEST+'overload_wait',));source=self.combo(g);presence=g.state.entities[source].board_presence_id
        self.assertEqual(g.state.players[1].overload_owed,2);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'bounce');self.choose(other,'bounce');self.assertEqual(g.snapshot(),other.snapshot())
        e=g.state.entities[source];self.assertNotEqual(e.board_presence_id,presence)
        self.assertNotIn(Keyword.IMMUNE,e.keywords);self.assertNotIn(Keyword.WINDFURY,e.keywords)
        self.assertEqual(g.state.players[1].overload_owed,2);self.portable(g)

    def test_aberration_original_grants_skip_dead_or_transferred_source_without_moving_debt(self):
        for branch in('kill','control'):
            with self.subTest(branch=branch):
                g=self.game((TEST+'noop',ABERRATION),(TEST+'overload_wait',));source=self.combo(g);self.choose(g,branch)
                self.assertNotIn(Keyword.IMMUNE,g.state.entities[source].keywords);self.assertNotIn(Keyword.WINDFURY,g.state.entities[source].keywords)
                self.assertEqual((g.state.players[1].overload_owed,g.state.players[2].overload_owed),(2,0))

    def test_aberration_countered_combo_never_overloads_or_grants(self):
        g=self.game((TEST+'noop',ABERRATION),enemy=(TEST+'counter',));source=self.combo(g)
        self.assertTrue(g.state.play_history[-1].countered);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.players[1].overload_owed,0);self.assertFalse(g.state.combo_history)

    def test_aberration_silence_clears_grants_without_erasing_overload(self):
        g=self.game((TEST+'noop',ABERRATION,TEST+'silence'));source=self.combo(g);self.play(g,TEST+'silence',source)
        self.assertNotIn(Keyword.WINDFURY,g.state.entities[source].keywords);self.assertNotIn(Keyword.IMMUNE,g.state.entities[source].keywords)
        self.assertEqual(g.state.players[1].overload_owed,2)

    def test_confinement_current_friendly_demon_and_all_tribes_get_only_buff(self):
        for cid in(TEST+'demon',TEST+'all'):
            with self.subTest(card=cid):
                g=self.game((CONFINEMENT,),(cid,));target=self.first(g,cid).id;self.play(g,CONFINEMENT,target)
                self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(4,6));self.assertIsNone(g.state.entities[target].dormancy)
                self.assertEqual(g.state.players[1].mana,38)

    def test_confinement_uses_current_demon_changes_and_all_exclusions(self):
        g=self.game((TEST+'demonify',CONFINEMENT),(TEST+'plain',));target=self.first(g,TEST+'plain').id
        self.play(g,TEST+'demonify',target);self.play(g,CONFINEMENT,target);self.assertEqual(g.state.entities[target].attack,4)
        g=self.game((TEST+'undemon',CONFINEMENT),(TEST+'all',));target=self.first(g,TEST+'all').id
        self.play(g,TEST+'undemon',target);self.play(g,CONFINEMENT,target);self.assertEqual(g.state.entities[target].attack,1)
        self.assertEqual(g.state.entities[target].dormancy.remaining_turns,2)

    def test_confinement_enemy_demon_or_friendly_other_type_uses_dormancy(self):
        for cid,owner in((TEST+'demon',2),(TEST+'plain',1)):
            with self.subTest(card=cid,owner=owner):
                g=self.game((CONFINEMENT,),(TEST+'plain',),enemy=(TEST+'demon',));target=self.first(g,cid,owner).id
                self.play(g,CONFINEMENT,target);self.assertEqual(g.state.entities[target].dormancy.remaining_turns,2)
                self.assertEqual(g.state.entities[target].attack,1)

    def test_confinement_two_actual_target_owner_starts_awaken_same_entity(self):
        g=self.game((CONFINEMENT,),enemy=(TEST+'plain',));target=self.first(g,TEST+'plain',2).id;self.play(g,CONFINEMENT,target);self.portable(g)
        self.end(g);self.assertEqual(g.state.entities[target].dormancy.remaining_turns,1)
        self.end(g);self.assertEqual(g.state.entities[target].dormancy.remaining_turns,1);self.end(g)
        self.assertIsNone(g.state.entities[target].dormancy);self.assertEqual(self.first(g,TEST+'plain',2).id,target);self.portable(g)

    def test_confinement_extra_and_skipped_target_owner_slots_use_original_countdown(self):
        for driver in(TEST+'extra_enemy',TEST+'skip_enemy'):
            with self.subTest(driver=driver):
                g=self.game((CONFINEMENT,driver),enemy=(TEST+'plain',));target=self.first(g,TEST+'plain',2).id
                self.play(g,CONFINEMENT,target);self.play(g,driver);self.end(g)
                if driver==TEST+'extra_enemy':
                    self.assertEqual(g.state.active_player,2);self.assertEqual(g.state.entities[target].dormancy.remaining_turns,1)
                    self.end(g);self.assertIsNone(g.state.entities[target].dormancy)
                else:self.assertEqual(g.state.active_player,1);self.assertEqual(g.state.entities[target].dormancy.remaining_turns,2)

    def test_confinement_unknown_friendly_tribe_rolls_back_but_enemy_needs_no_tribe_query(self):
        g=self.game((CONFINEMENT,),(TEST+'unknown',));target=self.first(g,TEST+'unknown').id;saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,CONFINEMENT,target)
        self.assertEqual(g.snapshot(),saved)
        g=self.game((CONFINEMENT,),enemy=(TEST+'unknown',));target=self.first(g,TEST+'unknown',2).id;self.play(g,CONFINEMENT,target)
        self.assertEqual(g.state.entities[target].dormancy.remaining_turns,2)

    def test_required_minion_and_friendly_beast_target_fail_before_payment(self):
        for cid in(CONFINEMENT,NATURE):
            with self.subTest(card=cid):
                g=self.game((cid,),(TEST+'plain',));saved=g.snapshot()
                with self.assertRaises(IllegalAction):self.play(g,cid)
                self.assertEqual(g.snapshot(),saved)
                if cid==NATURE:
                    with self.assertRaises(IllegalAction):self.play(g,cid,self.first(g,TEST+'plain').id)
                    self.assertEqual(g.snapshot(),saved)

    def test_both_spells_countered_have_no_buff_dormancy_random_or_hand_reward(self):
        for cid,target_card in((CONFINEMENT,TEST+'demon'),(NATURE,TEST+'beast')):
            with self.subTest(card=cid):
                g=self.game((cid,TEST+'beast'),(target_card,),enemy_hand=('EX1_287',),active=2)
                self.play(g,'EX1_287');self.end(g);target=self.first(g,target_card).id;rng=g._rng.getstate();self.play(g,cid,target)
                self.assertEqual(g.state.entities[target].attack,1);self.assertIsNone(g.state.entities[target].dormancy)
                self.assertEqual(self.first(g,TEST+'beast',zone='hand').attack,1);self.assertEqual(g._rng.getstate(),rng)

    def test_nature_buffs_board_beast_then_one_actual_hand_beast(self):
        g=self.game((NATURE,TEST+'beast'),(TEST+'beast',));target=self.first(g,TEST+'beast').id;self.play(g,NATURE,target)
        self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(3,5))
        hand=self.first(g,TEST+'beast',zone='hand');self.assertEqual((hand.attack,hand.health),(3,5))
        self.assertEqual(g.state.players[1].mana,38);self.portable(g)

    def test_nature_current_board_beast_and_player_predicate_agree_with_legal_targets(self):
        g=self.game((TEST+'beastify',NATURE),(TEST+'plain',));target=self.first(g,TEST+'plain').id
        self.play(g,TEST+'beastify',target);self.assertIsNone(g.for_player(1).legal_actions()['error']);self.play(g,NATURE,target)
        self.assertEqual(g.state.entities[target].attack,3)
        g=self.game((TEST+'unbeast',NATURE),(TEST+'beast',));target=self.first(g,TEST+'beast').id;self.play(g,TEST+'unbeast',target);saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,NATURE,target)
        self.assertEqual(g.snapshot(),saved);self.assertIsNone(g.for_player(1).legal_actions()['error'])

    def test_nature_hand_current_beast_includes_changed_plain_and_excludes_removed_printed_beast(self):
        g=self.game((TEST+'beastify',TEST+'unbeast',NATURE,TEST+'plain',TEST+'beast'),(TEST+'beast',))
        plain=self.first(g,TEST+'plain',zone='hand').id;beast=self.first(g,TEST+'beast',zone='hand').id
        self.play(g,TEST+'beastify',plain);self.play(g,TEST+'unbeast',beast);self.play(g,NATURE,self.first(g,TEST+'beast').id)
        self.assertEqual((g.state.entities[plain].attack,g.state.entities[beast].attack),(3,1));self.portable(g)

    def test_nature_random_physical_duplicate_and_all_tribe_weights_select_once(self):
        g=self.game((NATURE,TEST+'beast',TEST+'beast',TEST+'all',TEST+'plain'),(TEST+'beast',))
        candidates=[i for i in g.state.players[1].hand if g.state.entities[i].card_id in(TEST+'beast',TEST+'all')]
        probe=Random();probe.setstate(g._rng.getstate());selected=probe.choice(candidates)
        self.play(g,NATURE,self.first(g,TEST+'beast').id)
        self.assertEqual([i for i in candidates if g.state.entities[i].attack==3],[selected]);self.assertEqual(g._rng.getstate(),probe.getstate())
        self.assertEqual(self.first(g,TEST+'plain',zone='hand').attack,1);self.portable(g)

    def test_nature_empty_hand_candidates_keeps_rng_and_board_reward(self):
        g=self.game((NATURE,TEST+'plain'),(TEST+'beast',));rng=g._rng.getstate();target=self.first(g,TEST+'beast').id
        self.play(g,NATURE,target);self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.entities[target].attack,3)

    def test_nature_board_buff_wait_restores_and_second_stage_uses_changed_current_hand(self):
        g=self.game((NATURE,TEST+'plain',TEST+'beast'),(TEST+'board_wait',TEST+'beast'))
        target=self.first(g,TEST+'beast').id;self.play(g,NATURE,target);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'shift');self.choose(other,'shift');self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(self.first(g,TEST+'plain',zone='hand').attack,3);self.assertEqual(self.first(g,TEST+'beast',zone='hand').attack,1)
        self.portable(g)

    def test_nature_selected_hand_reward_wait_restores_without_repeating_rng(self):
        g=self.game((NATURE,TEST+'beast',TEST+'all'),(TEST+'hand_wait',TEST+'beast'));self.play(g,NATURE,self.first(g,TEST+'beast').id)
        rng=g._rng.getstate();other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g._rng.getstate(),rng)


if __name__=='__main__':unittest.main()
