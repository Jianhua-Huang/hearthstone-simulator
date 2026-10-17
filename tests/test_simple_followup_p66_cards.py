"""Real corpse/rune conditions and original native producer/combat boundaries."""
from dataclasses import asdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards import simple_followup_p66_cards as cards
from hs_sim.cards.simple_followup_p66_cards import (ANKYLODON,
    HOUND, SPEAR, MAIEV, VINE, HERENN, CHALLENGER, MANASTORM, SPLITTER, MUG, STORYTELLER, ROOTS, PREFIX, POOL_ID,
    load_batch, register_simple_followup_p66_cards)
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, IllegalAction, Keyword, PlayCard, PlayerSetup, Rarity, Resource, Runes, Scenario,
    SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.bonus_effects import BONUS_EFFECTS
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (ChoiceOption, Destroy, GainArmor, GrantDeathrattle,
    InvokeBehavior, ModifyCost, RequestChoice, ReturnToHand)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import CostSpec, LimitedTriggerSpec, SummonQuantitySpec, TribeChangeSpec
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

TEST = 'p66.test.'
A, B, CHILD, BEAST, DR1, DR2, UNDEAD, BLOOD, FROST, UNHOLY, ZERO, UNKNOWN, UNKNOWN_RUNE, WATCH = (
    TEST + s for s in ('a','b','child','beast','dr1','dr2','undead','blood','frost','unholy','zero','unknown','unknown_rune','watch'))
SPELL, KILL, AUTO, NOOP, DOUBLE, POWER, ATTACH, DISCOUNT, COUNTER = (
    TEST + s for s in ('spell','kill','auto','noop','double','power','attach','discount','counter'))
YETI = 'CORE_CS2_182'
DUAL, DRAGON, ELEMENTAL, ALLTYPE, UNKNOWN_TYPE, TRIBE = (TEST+s for s in ('dual','dragon','elemental','all','unknown_type','tribe'))
CONTEXT = GenerationContext('p66-complete-explicit-fixture', 'experimental')
MEMBERS = ((BEAST,2),(BLOOD,1),(FROST,1),(UNHOLY,1),(ZERO,1))
SOURCE_PIN = hashlib.sha256(Path(__file__).read_bytes() + Path(cards.__file__).read_bytes() + cards.BATCH_PATH.read_bytes()).hexdigest()


def meta(cls=CardClass.NEUTRAL, tribes=(), rune=Runes()):
    return CardMetadata(True, (cls,), Rarity.COMMON, runes=rune, tribes=tribes)


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None): r=build_registry()
    present=tuple(cid in r.cards for cid in ROOTS)
    if not any(present): register_simple_followup_p66_cards(r)
    elif not all(present): raise AssertionError('P66 requires complete assigned assembly')
    register_candidate_pool_metadata(r);r.validate();return r


def registry(mode=None,members=MEMBERS):
    r=batch_registry()
    r.register_behavior(TEST+'armor',lambda c:(GainArmor(c.player_id,1),))
    for cid,attack,health,tribes in ((A,20,20,()),(B,1,20,()),(CHILD,1,1,()),(BEAST,3,5,('beast',)),
            (UNDEAD,1,3,('undead',)),(DR1,1,10,()),(DR2,1,10,())):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=3,attack=attack,health=health,
            metadata=meta(tribes=tribes),deathrattle=TEST+'armor' if cid in (DR1,DR2) else None))
    for cid,tribes in ((DUAL,('beast','dragon')),(DRAGON,('dragon',)),(ELEMENTAL,('elemental',)),(ALLTYPE,('all',)),(UNKNOWN_TYPE,None)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=3,attack=1,health=5,metadata=meta(tribes=tribes)))
    for cid,runes in ((BLOOD,Runes(blood=1)),(FROST,Runes(frost=1)),(UNHOLY,Runes(unholy=1)),(ZERO,Runes())):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1,on_play=TEST+'noop',metadata=meta(CardClass.DEATH_KNIGHT,rune=runes)))
    r.register_card(CardDefinition(UNKNOWN_RUNE,'Unknown rune metadata',CardType.SPELL,cost=1,
        on_play=TEST+'noop',metadata=meta(CardClass.DEATH_KNIGHT,rune=None)))
    r.register_pool_card(PoolCard(UNKNOWN,CardType.SPELL,1,meta(CardClass.DEATH_KNIGHT,rune=Runes(blood=1)),
        battlecry=False,deathrattle=False,choose_one=False))
    r.register_card(CardDefinition(DOUBLE,'Native quantity source',CardType.MINION,health=20,
        summon_quantities=(SummonQuantitySpec(2),),metadata=meta()))
    r.register_card(CardDefinition(POWER,'Spell Damage witness',CardType.MINION,health=20,spell_damage=2,metadata=meta()))
    def fail(c):raise ResolutionError('P66 deliberate continuation failure')
    def reenter(c):return (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,cause=SummonCause.capture(c)),)
    def discount(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==SPELL)
        return (ModifyCost(e.id,CostSpec(set_to=0),c.source_id),)
    scripts={KILL:lambda c:(Destroy(c.target_id,c.source_id),),AUTO:lambda c:(CastSpell(c.player_id,SPELL,c.source_id),),
        SPELL:lambda c:(),NOOP:lambda c:(),ATTACH:lambda c:(GrantDeathrattle(c.target_id,TEST+'armor',c.source_id),),DISCOUNT:discount,
        TRIBE:lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',('dragon',)),c.source_id),)}
    r.register_behavior(TEST+'fail',fail);r.register_behavior(TEST+'reenter',reenter)
    for cid,body in scripts.items():
        r.register_behavior(cid,body);driver=cid==AUTO
        r.register_card(CardDefinition(cid,cid,CardType.MINION if driver else CardType.SPELL,cost=3 if cid==SPELL else 0,
            health=1 if driver else 0,battlecry=cid if driver else None,on_play=None if driver else cid,
            targeting=TargetSpec() if cid in (KILL,ATTACH,TRIBE) else None,metadata=meta()))
    r.register_behavior(TEST+'counter',lambda c:(CounterSpell(dict(c.event.data)['window_id']),)
        if c.event.player_id!=c.player_id and c.state.entities[c.event.source_id].kind==CardType.SPELL else ())
    r.register_card(CardDefinition(COUNTER,'Counter witness',CardType.MINION,health=20,
        triggers=(TriggerSpec('card_committed',TEST+'counter'),),metadata=meta()))
    for cid,_ in members:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition(POOL_ID,'p66-complete-finite-v1',CONTEXT.target_id,CONTEXT.mode,
        tuple(PoolMember(cid,w)for cid,w in members),complete=True))
    if mode:
        event=dict(entry='minion_summoned',battle='damage_dealt',bonus='ability_granted',buff='stats_changed')[mode]
        def eligible(c):
            if mode=='entry':return c.state.entities[c.event.target_id].card_id==BEAST
            source=c.state.entities.get(c.event.source_id)
            return source is not None and source.card_id==dict(battle=CHALLENGER,bonus=VINE,buff=MAIEV)[mode]
        def wait(c):
            target=c.event.source_id if mode=='battle' else c.event.target_id
            options=(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),)),
                ChoiceOption('kill','Original recipient dies',(Destroy(target,c.source_id),),entity_id=target),
                ChoiceOption('cycle','Original recipient leaves and reenters',(ReturnToHand(target),
                    InvokeBehavior(TEST+'reenter',c.source_id,c.state.entities[target].controller,target)),entity_id=target))
            return (RequestChoice(1,options,c.source_id),)
        r.register_trigger_condition(TEST+'eligible',eligible);r.register_behavior(TEST+'wait',wait)
        r.register_card(CardDefinition(WATCH,'Actual one-use checkpoint',CardType.MINION,health=20,
            limited_triggers=(LimitedTriggerSpec(event,TEST+'wait',condition_id=TEST+'eligible'),),metadata=meta()))
    return r


@lru_cache(maxsize=None)
def fixture_registry(mode,members,role,source_pin):
    if role not in ('writer','reader')or source_pin!=SOURCE_PIN:raise AssertionError('Incomplete immutable fixture key')
    r=registry(mode,members);r.freeze();return r


class SimpleFollowupP66Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),deck=(YETI,)*12,enemy_hand=(),weapon=None,corpses=0,mode=None,members=MEMBERS):
        self.config=mode,members
        if mode:board=(WATCH,)+board
        return Game.from_scenario(Scenario((PlayerSetup('HERO_11',hand=hand,board=board,deck=deck,
            weapon_card_id=weapon,corpses=corpses,mana=40,max_mana=40,mana_cap=40,hand_cap=None),
            PlayerSetup('HERO_11',hand=enemy_hand,board=enemy,deck=(YETI,)*12,mana=40,max_mana=40,mana_cap=40)),
            seed=6666,generation_context=CONTEXT),fixture_registry(mode,members,'writer',SOURCE_PIN))

    def first(self,g,cid,zone='hand',player=1):
        return next(g.state.entities[i]for i in getattr(g.state.players[player],zone)if g.state.entities[i].card_id==cid)

    def play(self,g,cid,target=None,player=1):
        e=self.first(g,cid,player=player);g.apply(PlayCard(player,e.id,target_id=target,
            position=len(g.state.players[player].board)if e.kind==CardType.MINION else None));return e.id

    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def portable(self,g):
        reader=fixture_registry(*self.config,'reader',SOURCE_PIN)
        self.assertIsNot(g.registry,reader);self.assertEqual(g.registry.fingerprint(),reader.fingerprint())
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,reader)
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);self.assertIsNot(g.state,other.state)
        for p in (1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in ('rng_state','resolution_frame','behavior_id','source_json','death_history','exclude_card_ids'):
                self.assertNotIn('"'+key+'"',public)
        return other

    def test_a0_ankylodon_actual_death_two_native_beasts_then_two_real_random_attacks(self):
        g=self.game(hand=(KILL,),board=(ANKYLODON,),enemy=(B,),members=((BEAST,1),))
        source=self.first(g,ANKYLODON,'board').id;self.play(g,KILL,source)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[BEAST,BEAST])
        self.assertEqual(len(g.state.character_attack_history),2)
        self.assertTrue(all(r.declaration.forced for r in g.state.character_attack_history))
        root=g.state.pool_summon_history[-1];self.assertEqual(root.status,'completed')
        self.assertEqual(root.spec.cause.source.entity_id,source);self.assertIsNone(root.spec.cause.cast_id);self.portable(g)

    def test_a1_herenn_actual_physical_deck_selections_fight_once_with_native_friendly_combat(self):
        g=self.game(hand=(HERENN,),deck=(DR1,DR2,B));original=set(g.state.players[1].deck[:2]);self.play(g,HERENN)
        self.assertEqual(set(g.state.players[1].board)&original,original)
        self.assertEqual(len(g.state.character_attack_history),1)
        row=g.state.character_attack_history[-1];self.assertEqual(row.declaration.combat_relation,'friendly_minions')
        self.assertEqual({row.declaration.source_id,row.delivery.target_id},original)
        self.assertTrue(all(g.state.entities[i].health==9 for i in original));self.assertEqual(len(g.state.players[1].deck),1);self.portable(g)

    def test_a2_challenger_repeats_actual_forced_attacks_until_original_source_dies(self):
        g=self.game(hand=(CHALLENGER,),enemy=(B,));enemy=self.first(g,B,'board',2).id;source=self.play(g,CHALLENGER,enemy)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[enemy].health,10)
        self.assertEqual(len(g.state.character_attack_history),10)
        self.assertTrue(all(row.declaration.forced and row.terminal.status=='completed'for row in g.state.character_attack_history));self.portable(g)

    def test_a3_manastorm_permanent_source_survives_death_and_real_paid_and_automatic_spells(self):
        g=self.game(hand=(MANASTORM,KILL,SPELL,AUTO),members=((BEAST,1),));source=self.play(g,MANASTORM)
        self.play(g,KILL,source);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.play(g,SPELL);self.play(g,AUTO)
        self.assertEqual(sum(g.state.entities[i].card_id==BEAST for i in g.state.players[1].board),2)
        self.assertEqual([r.origin for r in g.state.cast_history],['hand','hand','effect'])
        self.assertEqual(len(g.state.players[1].player_effects),1);self.portable(g)

    def test_a4_split_original_hand_spell_retirement_two_native_same_quote_generations_wait_restore(self):
        g=self.game(hand=(SPLITTER,BLOOD));target=self.first(g,BLOOD).id;self.play(g,SPLITTER)
        self.assertEqual(g.state.pending_choice.options[0].entity_id,target);other=self.portable(g)
        for running in (g,other):
            self.choose(running,running.state.pending_choice.options[0].id)
            self.assertEqual(running.state.entities[target].zone,Zone.GRAVEYARD)
            self.assertEqual(len(running.state.players[1].hand),2)
            self.assertTrue(all(running.registry.card(running.state.entities[i].card_id).cost==1 for i in running.state.players[1].hand))
            self.assertFalse(running.state.death_history);self.assertFalse(running.state.discard_history)
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g)

    def test_split_current_zero_quote_empty_hand_and_unknown_eligible_generation_rolls_back_selected_retirement(self):
        g=self.game(hand=(DISCOUNT,SPELL,SPLITTER),members=((NOOP,1),));self.play(g,DISCOUNT);self.play(g,SPLITTER)
        self.choose(g,g.state.pending_choice.options[0].id)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[NOOP,NOOP]);self.portable(g)
        g=self.game(hand=(SPLITTER,B));rng=g._rng.getstate();self.play(g,SPLITTER)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g._rng.getstate(),rng);self.portable(g)
        g=self.game(hand=(SPLITTER,BLOOD),members=((BLOOD,1),(UNKNOWN,1)));self.play(g,SPLITTER);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,g.state.pending_choice.options[0].id)
        self.assertEqual(g.snapshot(),saved);self.assertEqual(self.first(g,BLOOD).zone,Zone.HAND);self.portable(g)

    def test_mug_distinct_type_matching_keeps_dual_assignment_and_each_physical_group_one_weight(self):
        g=self.game(hand=(MUG,),board=(DUAL,BEAST,DRAGON,ELEMENTAL));ids=tuple(g.state.players[1].board)
        old={i:g.state.entities[i].attack for i in ids};source=self.play(g,MUG)
        self.assertEqual(sum(g.state.entities[i].attack-old[i] for i in ids),3)
        self.assertEqual(self.first(g,ELEMENTAL,'board').attack,2)
        self.assertEqual(g.state.entities[source].attack,3);self.portable(g)
        g=self.game(hand=(MUG,),board=(BEAST,BEAST));ids=tuple(g.state.players[1].board);self.play(g,MUG)
        self.assertEqual(sum(g.state.entities[i].attack-3 for i in ids),1);self.portable(g)

    def test_storyteller_maximum_current_type_group_all_wildcard_only_own_natural_end(self):
        g=self.game(board=(STORYTELLER,DUAL,BEAST,DRAGON,ELEMENTAL,ALLTYPE));ids=tuple(g.state.players[1].board)
        old={i:g.state.entities[i].attack for i in ids};g.apply(EndTurn(1))
        self.assertEqual(sum(g.state.entities[i].attack-old[i] for i in ids),4)
        after={i:g.state.entities[i].attack for i in ids};g.apply(EndTurn(2))
        self.assertEqual({i:g.state.entities[i].attack for i in ids},after);self.portable(g)
        g=self.game(board=(STORYTELLER,UNKNOWN_TYPE));saved=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(EndTurn(1))
        self.assertEqual(g.snapshot(),saved);self.portable(g)

    def test_distinct_groups_use_actual_current_tribe_changes_instead_of_printed_face(self):
        g=self.game(hand=(TRIBE,MUG),board=(BEAST,DRAGON));target=self.first(g,BEAST,'board').id
        self.play(g,TRIBE,target);old={i:g.state.entities[i].attack for i in g.state.players[1].board};self.play(g,MUG)
        self.assertEqual(sum(g.state.entities[i].attack-old[i] for i in old),1);self.portable(g)

    def test_complete_eleven_collectible_roots_eighteen_full_raws_twenty_two_strict_primary_faces(self):
        from tools.card_batch import check_face
        d=load_batch();rows={x['record']['id']:x['record']for k in ('cards','evidence_only')for x in d[k]}
        self.assertEqual((len(d['cards']),len(rows),len(d['official_observations'])),(11,18,22))
        self.assertEqual(tuple(d['collectible_candidate_roots']),ROOTS);self.assertFalse(d['noncollectible_ids'])
        for o in d['official_observations']:check_face(rows[o['card_id']],o['face'],o['locale'],d['display_normalizations'].get(o['card_id']))
        self.assertEqual(set(d['withdrawn_ids']),{'JAIL_909','JAIL_974','CORE_RLK_066','CORE_RLK_116','RLK_025'})
        self.assertFalse(d['formal_pool_complete']or d['cn_calibrated']or d['reachability_complete'])

    def test_old_full_definitions_pool_rows_and_core_edition_deck_identities_preserved(self):
        before,after=build_registry(),batch_registry()
        for cid,value in before.cards.items():self.assertEqual(after.card(cid),value)
        for cid,value in before.pool_cards.items():self.assertEqual(after.pool_card(cid),value)
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS)-set(before.cards))
        for cid in (CHALLENGER,MUG):self.assertEqual(after.card(cid).metadata.deck_identity,before.pool_card(cid).metadata.deck_identity)





    def test_ankylodon_original_entry_reentry_skips_attack_wait_restore_and_exception_rollback(self):
        g=self.game(hand=(KILL,),board=(ANKYLODON,),enemy=(B,),mode='entry',members=((BEAST,1),))
        self.play(g,KILL,self.first(g,ANKYLODON,'board').id);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(saved,g.snapshot());other=self.portable(g)
        for running in (g,other):
            self.choose(running,'cycle');self.assertEqual(len(running.state.character_attack_history),1)
            self.assertEqual(sum(running.state.entities[i].card_id==BEAST for i in running.state.players[1].board),2)
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g)

    def test_herenn_quantity_extras_do_not_replace_the_two_original_physical_deck_recipients(self):
        g=self.game(hand=(HERENN,),board=(DOUBLE,),deck=(DR1,DR2));original=set(g.state.players[1].deck);self.play(g,HERENN)
        self.assertEqual(len(g.state.players[1].board),6);self.assertEqual(len(g.state.character_attack_history),1)
        row=g.state.character_attack_history[-1];self.assertEqual({row.declaration.source_id,row.delivery.target_id},original)
        extras=[g.state.entities[i]for i in g.state.players[1].board if i not in original and g.state.entities[i].card_id in (DR1,DR2)]
        self.assertEqual([e.health for e in extras],[10,10]);self.portable(g)

    def test_herenn_fewer_than_two_or_full_board_never_invents_a_fighter(self):
        for board,deck in (((),(DR1,B)),((B,)*6,(DR1,DR2))):
            g=self.game(hand=(HERENN,),board=board,deck=deck);self.play(g,HERENN)
            self.assertFalse(g.state.character_attack_history);self.portable(g)

    def test_challenger_original_attacker_reentry_stops_remaining_combats_and_restores_wait(self):
        g=self.game(hand=(CHALLENGER,),enemy=(B,),mode='battle');self.play(g,CHALLENGER,self.first(g,B,'board',2).id)
        other=self.portable(g)
        for running in (g,other):self.choose(running,'cycle');self.assertEqual(len(running.state.character_attack_history),1)
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g)
        g=self.game(hand=(CHALLENGER,));rng=g._rng.getstate();self.play(g,CHALLENGER)
        self.assertFalse(g.state.character_attack_history);self.assertEqual(g._rng.getstate(),rng);self.portable(g)

    def test_hound_actual_surviving_minion_attack_native_whole_nonspell_budget_ignores_spell_damage(self):
        g=self.game(board=(HOUND,POWER),enemy=(B,));source=self.first(g,HOUND,'board').id;target=self.first(g,B,'board',2).id
        g.apply(Attack(1,source,target));hero=g.state.entities[g.state.players[2].hero_id]
        self.assertEqual(hero.health+g.state.entities[target].health,40)
        self.assertEqual(g.state.split_damage_history[-1].request.amount,5);self.portable(g)
        g=self.game(board=(HOUND,),enemy=(A,));g.apply(Attack(1,self.first(g,HOUND,'board').id,self.first(g,A,'board',2).id))
        self.assertFalse(g.state.split_damage_history);self.portable(g)
        g=self.game(board=(HOUND,),enemy=(B,));g.apply(Attack(1,self.first(g,HOUND,'board').id,g.state.players[2].hero_id))
        self.assertFalse(g.state.split_damage_history);self.portable(g)

    def test_spear_actual_hero_attack_excludes_original_defender_and_uses_current_hero_attack(self):
        for hero_target in (False,True):
            g=self.game(weapon=SPEAR,enemy=(B,));target=g.state.players[2].hero_id if hero_target else self.first(g,B,'board',2).id
            g.apply(Attack(1,g.state.players[1].hero_id,target))
            self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28)
            self.assertEqual(self.first(g,B,'board',2).health,18);self.portable(g)

    def test_maiev_excludes_own_play_buffs_original_other_minion_then_real_owner_countdown_wakes(self):
        g=self.game(hand=(MAIEV,B));source=self.play(g,MAIEV)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(1,3));self.assertTrue(g.state.entities[source].active)
        target=self.play(g,B);e=g.state.entities[target];self.assertEqual((e.attack,e.health),(4,23));self.assertFalse(e.active)
        self.portable(g);g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertTrue(g.state.entities[target].active);self.portable(g)

    def test_maiev_original_recipient_reentry_during_buff_does_not_sleep_new_body(self):
        g=self.game(hand=(B,),board=(MAIEV,),mode='buff');target=self.play(g,B);other=self.portable(g)
        for running in (g,other):self.choose(running,'cycle');self.assertTrue(running.state.entities[target].active)
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g)

    def test_vine_passes_only_its_own_stateless_deathrattle_with_bonus_then_recurs_from_new_carrier(self):
        g=self.game(hand=(KILL,KILL,ATTACH),board=(VINE,B));source=self.first(g,VINE,'board').id;target=self.first(g,B,'board').id
        self.play(g,ATTACH,source);self.play(g,KILL,source)
        granted=[a for a in g.state.entities[target].abilities if a.kind=='deathrattle'];self.assertEqual([a.behavior_id for a in granted],[PREFIX+'vine'])
        self.assertEqual(len(set(g.state.entities[target].keywords)&set(BONUS_EFFECTS)),1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1);self.portable(g)
        self.play(g,KILL,target);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1);self.portable(g)
        g=self.game(hand=(KILL,),board=(VINE,));rng=g._rng.getstate();self.play(g,KILL,self.first(g,VINE,'board').id)
        self.assertEqual(g._rng.getstate(),rng);self.portable(g)

    def test_vine_death_after_first_bonus_skips_grant_to_reentered_recipient_wait_rollback_restore(self):
        g=self.game(hand=(KILL,),board=(VINE,B),mode='bonus');self.play(g,KILL,self.first(g,VINE,'board').id);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(saved,g.snapshot());other=self.portable(g)
        for running in (g,other):
            self.choose(running,'cycle')
            self.assertFalse(any(a.kind=='deathrattle'and a.behavior_id==PREFIX+'vine'for i in running.state.players[1].board for a in running.state.entities[i].abilities))
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g)

    def test_manastorm_duplicates_stack_opponent_and_countered_spells_do_not_generate_and_printed_cost_policy(self):
        g=self.game(hand=(MANASTORM,MANASTORM,DISCOUNT,SPELL),members=((BEAST,1),));self.play(g,MANASTORM);self.play(g,MANASTORM)
        self.play(g,DISCOUNT);self.assertEqual(g.quote_cost(self.first(g,SPELL).id).amount,0);self.play(g,SPELL)
        self.assertEqual(sum(g.state.entities[i].card_id==BEAST for i in g.state.players[1].board),2);self.portable(g)
        g=self.game(hand=(MANASTORM,SPELL),enemy=(COUNTER,),enemy_hand=(SPELL,),members=((BEAST,1),));self.play(g,MANASTORM);self.play(g,SPELL)
        self.assertEqual(len(g.state.players[1].board),1);g.apply(EndTurn(1));self.play(g,SPELL,player=2)
        self.assertEqual(len(g.state.players[1].board),1);self.portable(g)

    def test_immutable_cached_reader_independent_and_wrong_registry_rejected_without_game_state_cache(self):
        g=self.game(hand=(SPLITTER,));reader=fixture_registry(*self.config,'reader',SOURCE_PIN)
        self.assertIsNot(g.registry,reader);self.assertIs(reader,fixture_registry(*self.config,'reader',SOURCE_PIN))
        with self.assertRaises(ValueError):reader.register_card(CardDefinition(TEST+'forbidden','Forbidden',CardType.MINION,health=1))
        wrong=registry(None,((BEAST,1),));wrong.freeze()
        with self.assertRaises(ValueError):Game.from_snapshot(g.snapshot(),wrong)
        self.portable(g)


if __name__=='__main__':unittest.main()
