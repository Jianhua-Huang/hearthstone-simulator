"""Actual pre-combat declarations, frozen body views and no invented event support."""
from dataclasses import asdict, replace, fields
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import assemble_attack_declared_followups as cards
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import POOL_ID as ASSEMBLE_POOL
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TriggerSpec)
from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleRecipe, SOURCE_FIELDS
from hs_sim.engine.assemble_reactions import AssembleReactionSource, REACTION_TIMINGS
from hs_sim.engine.effects import (Buff, ChoiceOption, Draw, GainArmor, InvokeBehavior,
    RequestChoice, ReturnToHand)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.interrupts import RedirectAttack
from hs_sim.engine.model import CardClass, LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha
from test_assemble_attack_finished_followups import fixture as base_fixture, DUMMY, BOOST
from test_assemble_card_play_followups import META, N, C, SP, KILL, COIN, WAR, CURATOR, LOOT, END, START

BROODMOTHER, SHAKU, RUNTHAK = cards.SOURCES
P = 'k425.'
PRE, WATCH, FAIL, UNKNOWN = (P + name for name in ('pre', 'watch', 'fail', 'unknown'))
MAGE, OWN, NEUTRAL = 'CORE_CS2_029', 'CORE_CS2_072', 'CORE_CS2_182'
CTX = GenerationContext('k425-reviewed-declaration-sources', 'experimental')
DECK = (COIN,) * 24
SHAKU_SELF = AssembleRecipe(SHAKU, SHAKU, 'bottom').card_id


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = base_fixture.__wrapped__('normal', role)
    r._version += '.k425.' + mode

    def fail(c):
        raise ResolutionError('K425 deliberate declaration failure')

    def pre(c):
        if c.event.player_id != 1 or c.event.source_id != c.state.players[1].board[1]:
            return ()
        if mode == 'draw_first':
            return (Draw(1, source_id=c.source_id),)
        if mode == 'redirect':
            target = next(eid for eid in c.state.players[2].board if c.state.entities[eid].card_id == N)
            return (RedirectAttack(dict(c.event.data)['window_id'], target),)
        effects = (Buff(c.event.source_id, attack=3, source_id=c.source_id),)
        if mode == 'wait_declaration':
            return (RequestChoice(1, (ChoiceOption('go', 'Buff before combat', effects),
                ChoiceOption('bad', 'Fail', (GainArmor(1, 1), InvokeBehavior(FAIL, c.source_id, 1)))), c.source_id),)
        return effects

    def watch(c):
        source = c.event.source_id
        if source is None or c.state.entities[source].card_id not in (SHAKU, SHAKU_SELF):
            return ()
        return (RequestChoice(1, (ChoiceOption('go', 'Continue'),
            ChoiceOption('bounce', 'Return accepted attacker', (ReturnToHand(source),)),
            ChoiceOption('bad', 'Fail', (GainArmor(1, 1), InvokeBehavior(FAIL, c.source_id, 1)))), c.source_id),)

    r.register_behavior(FAIL, fail)
    r.register_behavior(PRE, pre)
    r.register_behavior(WATCH, watch)
    r.register_trigger_condition(WATCH+'.eligible', lambda c: c.event.source_id is not None and
        c.state.entities[c.event.source_id].card_id in (SHAKU,SHAKU_SELF))
    r.register_card(CardDefinition(PRE, PRE, CardType.MINION, health=30, metadata=META,
        triggers=(TriggerSpec('attack_declared', PRE),)))
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=30, metadata=META,
        limited_triggers=(LimitedTriggerSpec('card_created', WATCH, condition_id=WATCH+'.eligible'),)))
    members = (OWN, NEUTRAL) if mode == 'empty_pool' else (MAGE, OWN, NEUTRAL)
    if mode == 'unknown_pool':
        missing = CardDefinition(UNKNOWN, UNKNOWN, CardType.SPELL, cost=1,
            metadata=replace(META, collectible=True, classes=(CardClass.MAGE,), deck_identity=UNKNOWN))
        r.register_pool_card(PoolCard.from_definition(missing))
        members += (UNKNOWN,)
    if mode != 'no_pool':
        r.register_pool(PoolDefinition(cards.POOL_ID, 'k425-full-explicit-other-class-domain',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    if mode == 'assemble':
        r.register_pool(PoolDefinition(ASSEMBLE_POOL, 'k425-real-three-five-five-domain',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in (SHAKU, RUNTHAK, WAR)), complete=True))
    r.validate()
    return r


class AssembleAttackDeclaredTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), enemy_hand=(), mode='normal', mana=0,
            active=1, hero='HERO_03', deck=DECK):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=hand, board=board, deck=deck, mana=mana, max_mana=10, mana_cap=10),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=DECK,
                mana=10, max_mana=10, mana_cap=10)), active_player=active, seed=425,
                generation_context=CTX), fixture(mode))

    def eid(self, game, cid, player=1, zone='board'):
        return next(eid for eid in getattr(game.state.players[player], zone) if game.state.entities[eid].card_id == cid)

    def play(self, game, cid, target=None):
        player = game.state.active_player; source = self.eid(game, cid, player, 'hand')
        game.apply(PlayCard(player, source, target)); return source

    def attack(self, game, cid, target=None):
        player = game.state.active_player; source = self.eid(game, cid, player)
        game.apply(Attack(player, source, target or game.state.players[3-player].hero_id)); return source

    def pick(self, game, key):
        choice = game.state.pending_choice
        game.apply(SelectChoice(choice.player_id, choice.id, (key,)))

    def portable(self, game, mode='normal'):
        saved = json.loads(json.dumps(game.snapshot())); reader = fixture(mode, 'reader')
        self.assertIsNot(reader, game.registry)
        restored = Game.from_snapshot(saved, reader)
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(game), reader).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(game.for_player(player).observe()) + json.dumps(game.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'condition_id', 'character_attack_history', 'played_face'):
                self.assertNotIn('"'+key+'"', public)
        return restored

    def test_a_four_complete_sources_eight_faces_and_exact_cumulative_plain_draw_extension(self):
        data = cards.load_batch(); r = fixture()
        rows = {row['record']['id']:row for row in data['existing_dependencies']}
        self.assertEqual(tuple(rows), cards.SOURCES+(WAR,))
        self.assertEqual(len(data['official_observations']), 8)
        for obs in data['official_observations']:
            self.assertEqual(sha(obs['response_file']), obs['response_sha256'])
            check_face(rows[obs['card_id']]['record'], obs['face'], obs['locale'])
        for cid,row in rows.items():
            self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
        for cid in cards.SOURCES:
            original=r.card(cid);template=r.assemble_templates[cid]
            self.assertEqual(template.prefix.timing,'attack_declared')
            self.assertEqual(r.assemble_reaction_sources[cid].original_behavior_id,original.triggers[0].behavior_id)
            d=r.card(AssembleRecipe(cid,cid,'bottom').card_id)
            self.assertEqual((d.cost,d.attack,d.health,d.keywords,d.metadata),
                (original.cost,original.attack,original.health,original.keywords,original.metadata))
        amendment=data['amendments'][0];old=amendment['old_template']
        current=json.loads(json.dumps(asdict(r.assemble_templates[WAR])))
        self.assertEqual(current['suffix']['allowed_timings'],old['suffix']['allowed_timings']+amendment['add_timings'])
        current['suffix']['allowed_timings']=old['suffix']['allowed_timings'];self.assertEqual(current,old)
        self.assertEqual(set(r.assemble_templates[WAR].suffix.allowed_timings),
            {'battlecry','deathrattle','end_turn','start_turn'}|set(REACTION_TIMINGS))

    def test_b_known_syntax_comes_from_complete_actual_roots_but_does_not_install_missing_card_effects(self):
        r=build_registry();covered=set()
        for cid,definition in r.cards.items():
            if definition.kind!=CardType.MINION or len(definition.triggers)!=1 or definition.triggers[0].end_turn is not None:
                continue
            default=CardDefinition(definition.id,definition.name,CardType.MINION)
            if all(getattr(definition,f.name)==getattr(default,f.name)for f in fields(CardDefinition)if f.name not in SOURCE_FIELDS):
                covered.add(definition.triggers[0].event)
        self.assertTrue(REACTION_TIMINGS<=covered)
        self.assertEqual(set(cards.load_batch()['ordinary_event_grammar']),REACTION_TIMINGS)
        self.assertNotIn('BE_996',r.assemble_templates)
        with self.assertRaises(ValueError):r.card(AssembleRecipe('BE_996',WAR,'bottom').card_id)
        with self.assertRaises(ValueError):AssemblePrefix('k425.fabricated_event',condition_id='x')
        r.register_trigger_condition(P+'fake',lambda c:True)
        with self.assertRaises(ValueError):r.register_assemble_reaction_source(AssembleReactionSource(
            BROODMOTHER,'minion_died',r.card(BROODMOTHER).triggers[0].behavior_id,P+'fake'))

    def test_c_original_and_self_broodmother_refresh_before_retaliation_and_cap_at_actual_maximum(self):
        for cid in (BROODMOTHER,AssembleRecipe(BROODMOTHER,BROODMOTHER,'bottom').card_id):
            for mana,expected in ((0,2),(9,10)):
                with self.subTest(cid=cid,mana=mana):
                    game=self.game(board=(cid,),enemy=(DUMMY,),mana=mana)
                    source=self.attack(game,cid,self.eid(game,DUMMY,2))
                    self.assertEqual((game.state.players[1].mana,game.state.players[1].max_mana),(expected,10))
                    self.assertEqual(game.state.entities[source].health,4)

    def test_d_original_and_self_shaku_use_current_hero_other_class_and_create_an_actual_playable_spell(self):
        for cid in (SHAKU,SHAKU_SELF):
            for hero,expected in (('HERO_03',MAGE),('HERO_08',OWN)):
                with self.subTest(cid=cid,hero=hero):
                    game=self.game(board=(cid,),mana=10,hero=hero);source=self.attack(game,cid)
                    self.assertEqual([game.state.entities[eid].card_id for eid in game.state.players[1].hand],[expected])
                    self.assertEqual(game.state.character_attack_history[-1].terminal.status,'completed')
                    self.assertNotIn(expected,json.dumps(game.for_player(2).observe())+json.dumps(game.player_events(2)))
                    if expected==MAGE:
                        self.play(game,MAGE,game.state.players[2].hero_id)
                        self.assertEqual(game.state.players[1].mana,6)
                        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health,22)

    def test_e_original_and_self_runthak_buff_only_original_hand_minions(self):
        for cid in (RUNTHAK,AssembleRecipe(RUNTHAK,RUNTHAK,'bottom').card_id):
            game=self.game((N,SP),(cid,))
            target=self.eid(game,N,zone='hand');spell=self.eid(game,SP,zone='hand')
            self.attack(game,cid)
            self.assertEqual((game.state.entities[target].attack,game.state.entities[target].max_health),(2,13))
            self.assertFalse(game.state.entities[spell].enchantments)

    def test_f_declared_window_keeps_original_captured_mana_quantity_despite_earlier_attack_buff(self):
        for cid in (BROODMOTHER,AssembleRecipe(BROODMOTHER,BROODMOTHER,'bottom').card_id):
            game=self.game(board=(PRE,cid),enemy=(DUMMY,),mode='buff_first')
            source=self.attack(game,cid,self.eid(game,DUMMY,2))
            self.assertEqual(game.state.players[1].mana,2)
            self.assertEqual(game.state.entities[source].attack,5)
            self.assertEqual(game.state.entities[self.eid(game,DUMMY,2)].health,35)

    def test_g_runthak_keeps_original_hand_reference_set_after_earlier_draw(self):
        for cid in (RUNTHAK,AssembleRecipe(RUNTHAK,RUNTHAK,'bottom').card_id):
            game=self.game((N,),(PRE,cid),mode='draw_first',deck=(C,)+DECK)
            old=self.eid(game,N,zone='hand');self.attack(game,cid)
            new=self.eid(game,C,zone='hand')
            self.assertEqual(game.state.entities[old].attack,2)
            self.assertEqual((game.state.entities[new].attack,game.state.entities[new].max_health),(1,12))

    def test_h_borrowed_declaration_prefix_draws_without_mana_generation_or_hand_buff_and_ignores_other_attackers(self):
        for donor in cards.SOURCES:
            cid=AssembleRecipe(donor,WAR,'bottom').card_id
            game=self.game((N,),(cid,C),mode='no_pool')
            self.attack(game,C);self.assertFalse(game.state.draw_history)
            self.attack(game,cid)
            self.assertEqual(len(game.state.draw_history),1)
            self.assertEqual(game.state.players[1].mana,0)
            self.assertEqual(game.state.entities[self.eid(game,N,zone='hand')].attack,1)

    def test_i_other_class_unknown_eligible_or_missing_domain_rolls_back_whole_attack_before_rng(self):
        for mode in ('unknown_pool','no_pool'):
            game=self.game(board=(SHAKU_SELF,),mode=mode);saved=game.snapshot()
            with self.assertRaisesRegex(ResolutionError,'(?i)(unimplemented|unsupported|eligible|definition|pool|domain)'):
                self.attack(game,SHAKU_SELF)
            self.assertEqual(game.snapshot(),saved)
        game=self.game(board=(SHAKU_SELF,),mode='empty_pool');rng=game.snapshot()['rng_state']
        self.attack(game,SHAKU_SELF)
        self.assertFalse(game.state.players[1].hand)
        self.assertEqual(game.snapshot()['rng_state'],rng)

    def test_j_true_generation_wait_retains_early_declaration_and_independent_restore_replay_cancelled_delivery(self):
        game=self.game(board=(WATCH,SHAKU_SELF));source=self.attack(game,SHAKU_SELF)
        self.assertIsNotNone(game.state.pending_choice)
        row=game.state.character_attack_history[-1]
        self.assertIsNone(row.combat);self.assertIsNone(row.terminal)
        saved=game.snapshot();reader=self.portable(game)
        with self.assertRaisesRegex(ResolutionError,'K425 deliberate'):self.pick(game,'bad')
        self.assertEqual(game.snapshot(),saved)
        self.pick(game,'bounce');self.pick(reader,'bounce')
        self.assertEqual(game.snapshot(),reader.snapshot())
        self.assertEqual(game.state.character_attack_history[-1].terminal.status,'cancelled')
        self.assertIn(source,game.state.players[1].hand)
        self.assertIn(MAGE,[game.state.entities[eid].card_id for eid in game.state.players[1].hand])
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health,30)
        self.portable(game)

    def test_k_declaration_wait_freezes_old_quantity_and_resumes_exactly_once_with_current_combat(self):
        cid=AssembleRecipe(BROODMOTHER,BROODMOTHER,'bottom').card_id
        game=self.game(board=(PRE,cid),enemy=(DUMMY,),mode='wait_declaration')
        self.attack(game,cid,self.eid(game,DUMMY,2))
        saved=game.snapshot();reader=self.portable(game,'wait_declaration')
        with self.assertRaisesRegex(ResolutionError,'K425 deliberate'):self.pick(game,'bad')
        self.assertEqual(game.snapshot(),saved)
        self.pick(game,'go');self.pick(reader,'go')
        self.assertEqual(game.snapshot(),reader.snapshot())
        self.assertEqual(game.state.players[1].mana,2)
        self.assertEqual(game.state.entities[self.eid(game,DUMMY,2)].health,35)
        self.assertEqual(len(game.state.character_attack_history),1)

    def test_l_original_declaration_target_survives_real_later_redirect_without_requiring_completed_record(self):
        game=self.game(board=(PRE,SHAKU_SELF),enemy=(N,),mode='redirect')
        hero=game.state.players[2].hero_id;self.attack(game,SHAKU_SELF)
        row=game.state.character_attack_history[-1]
        self.assertEqual(row.declaration.target_id,hero)
        self.assertEqual(row.delivery.target_id,self.eid(game,N,2))
        self.assertEqual(game.state.entities[hero].health,30)
        self.assertEqual([game.state.entities[eid].card_id for eid in game.state.players[1].hand],[MAGE])

    def test_m_three_independent_bodies_execute_at_battlecry_and_death_without_original_attack_guard(self):
        for donor in cards.SOURCES:
            for prefix in (CURATOR,LOOT):
                with self.subTest(donor=donor,prefix=prefix):
                    cid=AssembleRecipe(prefix,donor,'bottom').card_id
                    game=self.game((N,KILL),(cid,)) if prefix==LOOT else self.game((cid,N),mana=10)
                    before=game.state.players[1].mana
                    if prefix==LOOT:self.play(game,KILL,self.eid(game,cid))
                    else:self.play(game,cid)
                    self.assertFalse(game.state.character_attack_history)
                    if donor==BROODMOTHER:
                        expected=min(10,before+game.registry.card(prefix).attack) if prefix==LOOT else min(10,before-game.registry.card(prefix).cost+game.registry.card(prefix).attack)
                        self.assertEqual(game.state.players[1].mana,expected)
                    elif donor==SHAKU:self.assertIn(MAGE,[game.state.entities[eid].card_id for eid in game.state.players[1].hand])
                    else:self.assertEqual(game.state.entities[self.eid(game,N,zone='hand')].attack,2)

    def test_n_death_refresh_uses_own_actual_last_known_attack_and_real_spend(self):
        cid=AssembleRecipe(LOOT,BROODMOTHER,'bottom').card_id
        game=self.game((BOOST,KILL),(cid,));source=self.eid(game,cid)
        self.play(game,BOOST,source);self.play(game,KILL,source)
        self.assertEqual(game.state.death_history[-1].attack,5)
        self.assertEqual(game.state.players[1].mana,5)
        self.assertEqual(game.state.players[1].max_mana,10)

    def test_o_real_low_primary_offer_generates_paid_shaku_declaration_draw_without_old_generation(self):
        cid=AssembleRecipe(SHAKU,WAR,'bottom').card_id
        game=self.game((MISMATCH,),mode='assemble',mana=10);self.play(game,MISMATCH)
        choice=game.state.pending_choice
        self.pick(game,next(option.id for option in choice.options if option.card_id==cid))
        mana=game.state.players[1].mana;self.play(game,cid)
        self.assertEqual(game.state.players[1].mana,mana-3)
        game.apply(EndTurn(1));game.apply(EndTurn(2));before=len(game.state.draw_history)
        self.attack(game,cid)
        self.assertEqual(len(game.state.draw_history),before+1)
        self.assertNotIn(MAGE,[game.state.entities[eid].card_id for eid in game.state.players[1].hand])

    def test_p_physical_declaration_identity_no_event_wrong_window_or_target_and_old_core_are_refused(self):
        cid=AssembleRecipe(BROODMOTHER,WAR,'bottom').card_id
        game=self.game(board=(cid,));source=self.attack(game,cid)
        event=next(e for e in game.events if e.kind=='attack_declared')
        condition=game.registry.trigger_condition(cards.PREFIX+'own_declared_attack')
        context=RuleContext(game.state,source,1,event=event)
        self.assertTrue(condition(context))
        with self.assertRaises(ResolutionError):condition(replace(context,event=None))
        with self.assertRaises(ResolutionError):condition(replace(context,event=replace(event,target_id=source)))
        data=dict(event.data);data['window_id']=True
        with self.assertRaises(ResolutionError):condition(replace(context,event=replace(event,data=tuple(data.items()))))
        saved=json.loads(json.dumps(game.snapshot()));saved['mechanics_version']['version']='core-effects-v666'
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(ValueError):Game.from_snapshot(saved,fixture('normal','reader'))

    def test_q_complete_source_query_or_old_template_drift_refuses_before_partial_installation(self):
        with patch.object(cards,'register_assemble_attack_declared_followups',lambda r:None):r=build_registry()
        original=r.fingerprint()
        def registrations():
            return {key:dict(getattr(r,key)) for key in ('_cards','_pool_cards','_assemble_templates',
                '_assemble_reaction_sources','_trigger_conditions','_behaviors')}
        for cid in cards.SOURCES:
            old=r._cards[cid];pool=r._pool_cards[cid]
            r._cards[cid]=replace(old,cost=old.cost+1);r._pool_cards[cid]=replace(pool,cost=pool.cost+1)
            before=registrations()
            with self.assertRaisesRegex(TargetValidationError,'complete original source'):cards.register_assemble_attack_declared_followups(r)
            self.assertEqual(registrations(),before);r._cards[cid]=old;r._pool_cards[cid]=pool
        before=registrations()
        with patch.object(cards,'QUERY',replace(cards.QUERY,include_neutral=True)):
            with self.assertRaisesRegex(TargetValidationError,'original complete other-class query'):cards.register_assemble_attack_declared_followups(r)
        self.assertEqual(registrations(),before)
        old=r._assemble_templates[WAR]
        r._assemble_templates[WAR]=replace(old,suffix=replace(old.suffix,allowed_timings=old.suffix.allowed_timings+('attack_declared',)))
        before=registrations()
        with self.assertRaisesRegex(TargetValidationError,'exact reviewed plain draw template'):cards.register_assemble_attack_declared_followups(r)
        self.assertEqual(registrations(),before);r._assemble_templates[WAR]=old
        self.assertEqual(r.fingerprint(),original)
