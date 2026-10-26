"""Native Factory/Mini bodies and original-residence random character combat."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_nefarian_native_dependencies import fixture as base_fixture, FILLER
from hs_sim.cards.frontier_combat_and_mini import ROOTS, MINI, BOT, load_batch
from hs_sim.cards.past_summon_prices import PAST_TEN
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, Keyword,
    PlayerSetup, ResolutionError, Scenario, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Destroy, InvokeBehavior,
    RequestChoice, ReturnToHand)
from hs_sim.engine.forced_attack_sequences import AttackRandomEnemyCharacter
from hs_sim.engine.model import BoardPresenceReference
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember, resolve_candidates, sample_candidates
from hs_sim.engine.serialization import canonical_hash, SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference
from tools import card_batch as batch

S='k556.'
WATCH=S+'watch'
GIANT, LOCATION='OG_141','CORE_REV_990'
CTX=GenerationContext('k556-frontier-combat-test','experimental')


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    fmt=base_fixture.__wrapped__('normal',role);r=fmt.registry
    for name in ('constructed.cards','constructed.minions'):
        r.register_pool(replace(r.pool(name,fmt.context),target_id=CTX.target_id,mode=CTX.mode))
    r.register_pool(PoolDefinition('constructed.past.cards','two-native-combat-test-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in ROOTS),complete=True))
    def fail(c):raise ResolutionError('k556 deliberate late failure')
    def reenter(c):
        e=c.state.entities[c.target_id]
        return (SummonStoredCard(CardReference.capture(e),e.controller,cause=SummonCause.capture(c)),)
    def wait(c,target,defender=None):
        options=[ChoiceOption('continue','Continue'),
            ChoiceOption('kill','Destroy original',(Destroy(target,c.source_id),)),
            ChoiceOption('transfer','Transfer original',(ChangeControl(target,3-c.player_id),)),
            ChoiceOption('reenter','Reenter same physical actor',(ReturnToHand(target),
                InvokeBehavior(S+'reenter',c.source_id,c.player_id,target))),
            ChoiceOption('fault','Fail',(InvokeBehavior(S+'fail',c.source_id,c.player_id),))]
        if defender is not None and c.state.entities[defender].kind==CardType.MINION:
            owner=c.state.entities[defender].controller
            options.append(ChoiceOption('defender','Reenter selected physical defender',(ReturnToHand(defender),
                InvokeBehavior(S+'reenter',c.source_id,owner,defender))))
        return RequestChoice(c.player_id,tuple(options),c.source_id)
    def attack(c):
        target=next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==BOT)
        effect=AttackRandomEnemyCharacter(BoardPresenceReference.capture(c.state,target),c.player_id,c.source_id)
        return (wait(c,target),effect)if mode=='delayed'else (effect,)
    def observe(c):
        if mode=='bot_wait' and c.event.kind=='minion_summoned':
            e=c.state.entities[c.event.target_id]
            if e.card_id==BOT and e.controller==c.player_id:return (wait(c,e.id),)
        if mode=='random_wait' and c.event.kind=='random_choice':
            data=dict(c.event.data)
            if data.get('producer')=='attack_random_enemy_character':
                return (wait(c,c.event.target_id,data['defender_id']),)
        return ()
    for name,body in (('fail',fail),('reenter',reenter),('attack',attack)):
        r.register_behavior(S+name,body)
        r.register_card(CardDefinition(S+name,name,CardType.SPELL,on_play=S+name))
    r.register_behavior(S+'observe',observe)
    r.register_card(CardDefinition(WATCH,'Diagnostic combat observer',CardType.WEAPON,attack=0,durability=30,
        triggers=tuple(TriggerSpec(k,S+'observe')for k in ('minion_summoned','random_choice'))))
    r.validate();return replace(fmt,context=CTX)


def wires(value,name):
    if isinstance(value,dict):
        if value.get('type','').endswith('.'+name):yield value
        for child in value.values():yield from wires(child,name)
    elif isinstance(value,list):
        for child in value:yield from wires(child,name)


class FrontierCombatMiniTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:fixture(mode,role).registry)

    def game(self,hand=(),*,board=(),enemy=(),mode='normal',seed=1):
        self.mode=mode;fmt=fixture(mode)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_06',hand=hand,board=board,deck=(FILLER,)*6,max_mana=10,mana=10,
                weapon_card_id=WATCH if mode!='normal'else None),
            PlayerSetup('HERO_08',board=enemy,deck=(FILLER,)*6,max_mana=10,mana=10)),
            seed=seed,generation_context=CTX),fmt.registry)

    def selections(self,g):
        return [e for e in g.events if e.kind=='random_choice' and
            dict(e.data).get('producer')=='attack_random_enemy_character']

    def test_all_four_complete_rows_eight_primary_faces_and_native_declarations(self):
        data=load_batch();source={r['id']:r for r in batch.read(data['source'])}
        rows={x['record']['id']:x['record']for key in ('cards','dependencies')for x in data[key]}
        self.assertEqual(set(rows),{*ROOTS,MINI,BOT});self.assertEqual(batch.sha(data['source']),data['source_sha256'])
        r=fixture().registry
        for cid,raw in rows.items():
            self.assertEqual(raw,source[cid]);card=r.card(cid)
            self.assertEqual((card.cost,card.attack,card.health),tuple(raw[k]for k in ('cost','attack','health')))
        for face in data['official_faces']:batch.check_face(rows[face['card_id']],face['face'],face['locale'])
        self.assertEqual(r.card('TOY_601').keywords,(Keyword.MINIATURIZE,))
        self.assertEqual((r.card(MINI).keywords,r.card(MINI).hand_derivatives),((Keyword.MINI,),()))
        self.assertEqual(r.card('DMF_070').keywords,(Keyword.RUSH,Keyword.POISONOUS));self.assertTrue(r.card('DMF_070').cleave)
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])

    def test_real_factory_payment_mini_generation_and_enemy_hero_is_a_valid_target(self):
        g=self.game(('TOY_601',));root=self.play(g,'TOY_601');mini=self.entity(g,MINI)
        self.assertEqual((g.state.players[1].mana,mini.attack,mini.health),(0,1,1))
        g.apply(EndTurn(1));bot=self.entity(g,BOT,zone='board');hero=g.state.players[2].hero_id
        self.assertEqual((bot.attack,bot.health,g.state.entities[hero].health),(6,7,24))
        self.assertEqual(dict(self.selections(g)[0].data)['defender_id'],hero)
        self.assertEqual(g.state.card_summon_history[-1].request.cause.source.entity_id,root)
        self.assertEqual(len(g.state.character_attack_history),1);self.portable(g)

    def test_terminal_mini_produces_a_real_six_seven_and_uses_only_controller_end_clock(self):
        g=self.game(('TOY_601',));self.play(g,'TOY_601');g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual(len(self.selections(g)),1);mini=self.play(g,MINI)
        self.assertFalse(any(g.state.entities[i].card_id==MINI for i in g.state.players[1].hand))
        g.apply(EndTurn(1));bots=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==BOT]
        self.assertEqual([(b.attack,b.health)for b in bots],[(6,7)]*3)
        self.assertEqual(len(self.selections(g)),3)
        self.assertEqual(g.state.card_summon_history[-1].request.cause.source.entity_id,mini)

    def test_rush_poisonous_cleave_kills_primary_and_both_neighbors_after_retaliation(self):
        g=self.game(('DMF_070',),enemy=(GIANT,)*3);rabbit=self.play(g,'DMF_070');targets=tuple(g.state.players[2].board)
        g.apply(Attack(1,rabbit,targets[1]))
        self.assertEqual([g.state.entities[i].zone for i in (*targets,rabbit)],[Zone.GRAVEYARD]*4)
        self.assertEqual(len(g.state.character_attack_history),1);self.portable(g)

    def test_primary_divine_shield_prevents_poison_while_both_neighbors_still_die(self):
        g=self.game(('DMF_070',),enemy=(GIANT,'DEEP_006',GIANT));rabbit=self.play(g,'DMF_070')
        left,middle,right=g.state.players[2].board;g.apply(Attack(1,rabbit,middle))
        self.assertEqual([g.state.entities[i].zone for i in (left,right,rabbit)],[Zone.GRAVEYARD]*3)
        self.assertEqual((g.state.entities[middle].zone,g.state.entities[middle].damage),(Zone.BOARD,0))
        self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[middle].keywords)

    def test_random_characters_include_hero_and_stealth_minion_but_exclude_location(self):
        selected=set()
        for seed in range(6):
            g=self.game((S+'attack',),board=(BOT,),enemy=(FILLER,LOCATION),seed=seed)
            hero=g.state.players[2].hero_id;minion,location=g.state.players[2].board
            self.play(g,S+'attack');choice,=self.selections(g);target=dict(choice.data)['defender_id']
            self.assertIn(target,(hero,minion));self.assertNotEqual(target,location);selected.add(target)
            self.assertEqual(len(g.state.character_attack_history),1)
        self.assertEqual(selected,{hero,minion})

    def test_old_attacker_reentry_transfer_or_death_skips_without_reroll(self):
        for branch in ('reenter','transfer','kill'):
            with self.subTest(branch=branch):
                g=self.game((S+'attack',),board=(BOT,),mode='delayed');actor=self.entity(g,BOT,zone='board').id
                original=BoardPresenceReference.capture(g.state,actor);self.play(g,S+'attack');rng=g.snapshot()['rng_state']
                self.choose(g,branch);self.assertFalse(self.selections(g));self.assertEqual(g.snapshot()['rng_state'],rng)
                self.assertFalse(g.state.character_attack_history)
                if branch=='reenter':
                    self.assertEqual(self.entity(g,BOT,zone='board').id,actor)
                    self.assertNotEqual(BoardPresenceReference.capture(g.state,actor),original)

    def test_queued_new_selector_wait_restore_replay_and_failed_resume_are_atomic(self):
        g=self.game((S+'attack',),board=(BOT,),mode='delayed');self.play(g,S+'attack')
        saved=g.snapshot();other=self.portable(g)
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
        for game in (g,other):self.choose(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.selections(g)),1)
        self.assertEqual(len(g.state.character_attack_history),1)

    def test_actual_summon_wait_restores_before_original_named_attack_and_death_cancels(self):
        g=self.game(('TOY_601',),mode='bot_wait');self.play(g,'TOY_601');g.apply(EndTurn(1))
        self.assertIsNotNone(g.state.pending_choice);self.assertFalse(self.selections(g));other=self.portable(g)
        saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
        for game in (g,other):self.choose(game,'kill')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertFalse(self.selections(g))
        self.assertFalse(g.state.character_attack_history);self.assertEqual(len(g.state.players[1].board),1)

    def test_selected_target_and_rng_survive_wait_and_continue_exactly_once(self):
        g=self.game(('TOY_601',),mode='random_wait');self.play(g,'TOY_601');g.apply(EndTurn(1))
        self.assertEqual(len(self.selections(g)),1);self.assertFalse(g.state.character_attack_history)
        other=self.portable(g);rng=g.snapshot()['rng_state']
        for game in (g,other):self.choose(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.snapshot()['rng_state'],rng)
        self.assertEqual(len(self.selections(g)),1);self.assertEqual(len(g.state.character_attack_history),1)

    def test_selected_minion_reentry_cancels_saved_original_defender_without_reroll(self):
        g=self.game((S+'attack',),board=(BOT,),enemy=(FILLER,),mode='random_wait',seed=0)
        self.play(g,S+'attack');choice,=self.selections(g);defender=dict(choice.data)['defender_id']
        self.assertEqual(g.state.entities[defender].kind,CardType.MINION);other=self.portable(g);rng=g.snapshot()['rng_state']
        for game in (g,other):self.choose(game,'defender')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.snapshot()['rng_state'],rng)
        self.assertEqual(g.state.entities[defender].damage,0);self.assertFalse(g.state.character_attack_history)

    def test_full_board_factory_has_no_delivery_attack_or_rng_consumption(self):
        g=self.game(board=('TOY_601',)+(FILLER,)*6);rng=g.snapshot()['rng_state'];g.apply(EndTurn(1))
        self.assertEqual(len(g.state.players[1].board),7);self.assertFalse(self.selections(g))
        self.assertFalse(g.state.character_attack_history);self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_unknown_future_residence_and_previous_schema_are_rejected(self):
        g=self.game((S+'attack',),board=(BOT,),mode='delayed');self.play(g,S+'attack');saved=g.snapshot()
        for entity,presence in ((999999,1),(self.entity(g,BOT,zone='board').id,g.state.next_order)):
            with self.subTest(entity=entity,presence=presence):
                edited=deepcopy(saved);wire=next(wires(edited['resolution_frame'],'AttackRandomEnemyCharacter'))
                wire['fields']['attacker']['fields'].update(entity_id=entity,presence_id=presence)
                edited['state_hash']=canonical_hash({k:v for k,v in edited.items()
                    if k not in ('schema_version','events','events_hash','state_hash')})
                with self.assertRaises((SnapshotError,ValueError)):Game.from_snapshot(edited,fixture('delayed').registry)
        saved['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,fixture('delayed').registry)

    def test_both_roots_really_pass_frontier_discovery_and_one_mana_hand_play(self):
        candidates=resolve_candidates(fixture().registry,CTX,'constructed.past.cards',PAST_TEN,
            current_class=fixture().registry.card('CFM_308').metadata.classes[0],source_card_id='GDB_857',player_id=1)
        self.assertEqual({x.card_id for x in candidates},set(ROOTS))
        for cid in ROOTS:
            seed=next(n for n in range(100)if cid in sample_candidates(Random(n),candidates,3,replacement=False))
            g=self.game(('GDB_857',),seed=seed);self.play(g,'GDB_857')
            self.choose(g,next(o.id for o in g.state.pending_choice.options if o.card_id==cid))
            source=self.play(g,cid);self.assertEqual((g.state.entities[source].card_id,g.state.play_history[-1].cost),(cid,1))
            if cid=='TOY_601':self.assertEqual(self.entity(g,MINI).card_id,MINI)


if __name__=='__main__':unittest.main()
