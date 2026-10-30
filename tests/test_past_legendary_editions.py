"""Actual original identities reuse native effects through real paid actions."""
from dataclasses import asdict,replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_legendary_editions as native
from hs_sim.engine import (Attack,EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario,SelectChoice,UseHeroPower)
from hs_sim.engine.effects import (ChoiceOption,Damage,Destroy,Draw,InvokeBehavior,RandomDamage,RequestChoice,Silence,Summon)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.model import (CardDefinition,CardType,DamageKind,Keyword,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.registry import Registry
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import CardReference
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest

MAYOR,SHAKU,KHADGAR,DRAGONBANE,NATALIE,JAILER,ALAKIR,MOGRAINE,WILLOW,ALABASTER,BOLVAR,KRAGWA,HALAZZI,SIAMAT=native.ROOTS
A='CORE_CS2_182';LYNX='TRL_348t';FIREBALL='CS2_029';HP='HERO_08bp'
P='k694.';KILL=P+'kill';HUSH=P+'hush';HIT=P+'hit';DRAW=P+'draw';MAKE=P+'make';PLAIN=P+'plain'
PREPARE=P+'prepare_deck';DEMON=P+'demon';FAIL=P+'fail';WATCH=P+'watch'
COPY_WATCH=P+'copy_watch';SUMMON_WATCH=P+'summon_watch';DAMAGE_WATCH=P+'damage_watch'
HELPERS=(KILL,HUSH,HIT,DRAW,MAKE,PLAIN,PREPARE,DEMON,COPY_WATCH,SUMMON_WATCH,DAMAGE_WATCH)


@lru_cache(None)
def host(role='writer'):
    h=build_cn37_local_pool_format();r=h.registry
    meta=replace(metadata(collectible=False),tribes=())
    r.register_card(CardDefinition(DEMON,DEMON,CardType.MINION,cost=2,attack=3,health=7,
        metadata=replace(meta,tribes=('demon',))))
    def prepare(c):
        entity=c.state.entities[c.state.players[2].deck[0]]
        return(BuffStoredCard(CardReference.capture(entity),2,3,c.source_id),)
    scripts={KILL:lambda c:(Destroy(c.target_id,c.source_id),),HUSH:lambda c:(Silence(c.target_id),),
        HIT:lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL),),
        DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),
        MAKE:lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(A),),SummonCause.capture(c)),),
        PLAIN:lambda c:(Summon(c.player_id,A),),PREPARE:prepare}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1,on_play=cid,
            metadata=meta,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if cid in(KILL,HUSH,HIT)else None))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K694 deliberate original native continuation failure')))
    def watch(c):
        source=c.state.entities.get(c.event.source_id);target=c.state.entities.get(c.event.target_id)
        retire=()
        if c.event.kind=='minion_summoned':
            if target is None or target.card_id!=A:return()
            provider=next((i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==KHADGAR),None)
            if provider is not None:retire=(Destroy(provider,c.source_id),)
        elif c.event.kind=='card_created':
            if source is None or source.card_id not in(SHAKU,ALABASTER):return()
        elif source is None or source.card_id!=MOGRAINE:return()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('retire','Retire provider',retire),
            ChoiceOption('fault','Fail after random work',(
                RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    for cid,event in((COPY_WATCH,'card_created'),(SUMMON_WATCH,'minion_summoned'),(DAMAGE_WATCH,'damage_dealt')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=30,metadata=meta,triggers=(TriggerSpec(event,WATCH),)))
    r.validate();return h


@lru_cache(None)
def fixture(role='writer'):
    full=host(role).registry;r=Registry('k694-complete-native-fixture-v1')
    for bid,body in full._behaviors.items():
        if bid not in r._behaviors and not bid.startswith(native.PREFIX):r.register_behavior(bid,body)
    ids=tuple('CORE_'+cid for cid in native.ROOTS)+(A,LYNX,FIREBALL,'TIME_013','HERO_08',HP,*HELPERS)
    for cid in ids:
        r.register_card(full.card(cid))
        if cid in full.pool_cards:r.register_pool_card(full.pool_card(cid))
    r.register_player_effect(full.player_effect(native.EXISTING_PROGRAM))
    r.register_random_target_card('CORE_CFM_670')
    native.register_past_legendary_editions(r);r.validate();return r


class PastLegendaryEditionTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=(A,)*8,enemy_deck=(A,)*8,player=1,real_host=False):
        self.mode='host'if real_host else'small';h=host('writer');r=h.registry if real_host else fixture('writer')
        return Game.from_scenario(Scenario(tuple(PlayerSetup('HERO_08',hand=hand if p==player else enemy_hand,
            board=board if p==player else enemy,deck=deck if p==player else enemy_deck,hero_power_card_id=HP,
            mana=30,max_mana=30,mana_cap=30)for p in(1,2)),active_player=player,seed=694,
            generation_context=h.context if real_host else None),r)
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def power(self,g,target,p=1):g.apply(UseHeroPower(p,g.state.players[p].hero_power_ids[0],target))
    def finish(self,g):
        while g.state.pending_choice is not None:
            q=g.state.pending_choice
            g.apply(SelectChoice(q.player_id,q.id,('rush','windfury')if q.min_count==2 else('continue',)))
    def created(self,g,source):return[g.state.entities[e.target_id]for e in g.events if e.kind=='card_created'and e.source_id==source]

    def test_complete_fourteen_original_faces_keep_full_roles_and_semantic_tags(self):
        d=native.load_batch();self.assertEqual(len(d['original_candidate_ids']),732);self.assertEqual(len(d['official_observations']),32)
        for row,core in zip(d['cards'],d['existing_dependencies']):
            native.semantic_pair(row['record'],core['record']);cid=row['record']['id']
            self.assertEqual(canonical_digest(asdict(fixture().card(cid))),row['definition_sha256'])
            self.assertEqual(canonical_digest(asdict(fixture().pool_card(cid))),row['pool_card_sha256'])
            self.assertNotEqual(row['record']['card_set_id'],core['record']['card_set_id'])

    def test_all_fourteen_actual_paid_entries_keep_original_stats_and_ids(self):
        for cid in native.ROOTS:
            g=self.game((cid,));source=self.play(g,cid);self.finish(g);printed=g.registry.card(cid)
            self.assertEqual((g.state.entities[source].card_id,g.state.entities[source].attack,g.state.entities[source].health),(cid,printed.attack,printed.health))
            self.assertEqual(g.state.players[1].mana,30-printed.cost)

    def test_original_mayor_has_its_own_source_marker_and_keeps_manual_proposal(self):
        g=self.game((HIT,),board=(MAYOR,),enemy=(A,));target=self.unit(g,A,2).id;self.play(g,HIT,target)
        self.assertIn(MAYOR,g.registry.random_target_cards)
        self.assertEqual(g.state.play_history[-1].target_id,target)
        self.assertEqual(sum(e.kind=='native_manual_target_selected'for e in g.events),1);self.portable(g)

    def test_original_mayor_silence_retires_random_source_without_new_target_executor(self):
        g=self.game((HUSH,HIT),board=(MAYOR,));source=self.unit(g,MAYOR).id;self.play(g,HUSH,source)
        old=sum(e.kind=='native_manual_target_selected'for e in g.events);self.play(g,HIT,source)
        self.assertEqual(sum(e.kind=='native_manual_target_selected'for e in g.events),old)

    def test_original_khadgar_doubles_card_caused_summon_and_rejects_unattributed_request(self):
        g=self.game((MAKE,PLAIN),board=(KHADGAR,));self.play(g,MAKE)
        self.assertEqual(sum(g.state.entities[i].card_id==A for i in g.state.players[1].board),2)
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,PLAIN)
        self.assertEqual(g.snapshot(),before)

    def test_original_khadgar_two_physical_sources_multiply_and_silence_removes_one(self):
        g=self.game((MAKE,),board=(KHADGAR,KHADGAR));self.play(g,MAKE)
        self.assertEqual(sum(g.state.entities[i].card_id==A for i in g.state.players[1].board),4)
        g=self.game((HUSH,MAKE),board=(KHADGAR,));self.play(g,HUSH,self.unit(g,KHADGAR).id);self.play(g,MAKE)
        self.assertEqual(sum(g.state.entities[i].card_id==A for i in g.state.players[1].board),1)

    def test_original_khadgar_first_summon_wait_retains_accepted_units_after_provider_death(self):
        g=self.game((MAKE,),board=(KHADGAR,SUMMON_WATCH));self.play(g,MAKE);before=g.snapshot();g=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g,'retire');self.finish(g)
        self.assertEqual(sum(g.state.entities[i].card_id==A for i in g.state.players[1].board),2);self.portable(g)

    def test_original_alakir_four_printed_keywords_have_real_attack_budget_and_shield(self):
        g=self.game((ALAKIR,),enemy=(LYNX,));source=self.play(g,ALAKIR)
        self.assertEqual(g.state.entities[source].keywords,{Keyword.CHARGE,Keyword.DIVINE_SHIELD,Keyword.TAUNT,Keyword.WINDFURY})
        g.apply(Attack(1,source,self.unit(g,LYNX,2).id));self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[source].keywords)
        g.apply(Attack(1,source,self.hero(g,2).id));before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(Attack(1,source,self.hero(g,2).id))
        self.assertEqual(g.snapshot(),before)

    def test_original_dragonbane_uses_actual_own_completed_power_and_nonspell_five_damage(self):
        g=self.game(board=(DRAGONBANE,));self.power(g,self.hero(g,2).id)
        self.assertEqual(self.hero(g,2).health,24);self.assertEqual(g.state.players[1].mana,28)
        g=self.game(board=(DRAGONBANE,));self.end(g);self.power(g,self.hero(g).id,2)
        self.assertEqual(self.hero(g).health,29);self.assertEqual(self.hero(g,2).health,30)

    def test_original_dragonbane_silenced_source_does_not_trigger(self):
        g=self.game((HUSH,),board=(DRAGONBANE,));self.play(g,HUSH,self.unit(g,DRAGONBANE).id);self.power(g,self.hero(g,2).id)
        self.assertEqual(self.hero(g,2).health,29)

    def test_original_natalie_destroys_actual_wounded_target_and_gains_remaining_health(self):
        g=self.game((HIT,NATALIE),enemy=(A,));target=self.unit(g,A,2).id;self.play(g,HIT,target);amount=g.state.entities[target].health
        source=self.play(g,NATALIE,target);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[source].health,g.registry.card(NATALIE).health+amount);self.portable(g)

    def test_original_natalie_no_available_target_is_legal_and_heroes_are_rejected(self):
        g=self.game((NATALIE,));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,NATALIE,self.hero(g,2).id)
        self.assertEqual(g.snapshot(),before);self.play(g,NATALIE)

    def test_original_jailer_destroys_own_complete_deck_and_grants_only_its_own_immunity(self):
        g=self.game((JAILER,),board=(A,),deck=(A,LYNX));source=self.play(g,JAILER)
        self.assertFalse(g.state.players[1].deck);self.assertEqual(len(g.state.players[2].deck),8)
        self.assertIn(Keyword.IMMUNE,g.state.entities[source].keywords);self.assertNotIn(Keyword.IMMUNE,self.unit(g,A).keywords)
        self.assertFalse(any(e.kind=='card_drawn'for e in g.events));self.portable(g)

    def test_original_mograine_permanent_program_survives_source_death_and_only_own_ends(self):
        g=self.game((MOGRAINE,KILL));source=self.play(g,MOGRAINE);self.play(g,KILL,source)
        spec=g.state.players[1].player_effects[0];self.assertEqual((spec.spec_id,spec.source_card_id),(native.PROGRAM,MOGRAINE))
        self.end(g);self.assertEqual(self.hero(g,2).health,27);self.end(g);self.assertEqual(self.hero(g,2).health,27)
        self.end(g);self.assertEqual(self.hero(g,2).health,24);self.portable(g)

    def test_original_and_core_mograine_have_separate_programs_and_actual_source_identities(self):
        g=self.game((MOGRAINE,'CORE_RLK_706'));source=self.play(g,MOGRAINE);core=self.play(g,'CORE_RLK_706')
        rows=g.state.players[1].player_effects;self.assertEqual({x.source_id for x in rows},{source,core})
        self.assertEqual({g.registry.player_effect(x.spec_id).card_id for x in rows},{MOGRAINE,'CORE_RLK_706'})
        self.end(g);self.assertEqual(self.hero(g,2).health,24);self.portable(g)

    def test_original_mograine_future_damage_wait_restores_original_source_and_failure(self):
        g=self.game((MOGRAINE,),board=(DAMAGE_WATCH,));self.play(g,MOGRAINE);self.end(g);before=g.snapshot();g=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.finish(g);self.assertEqual(self.hero(g,2).health,27);self.portable(g)

    def test_original_willow_summons_original_hand_and_deck_demons_without_battlecries(self):
        g=self.game((WILLOW,DEMON),deck=(A,DEMON));hand=self.entity(g,DEMON).id;deck=g.state.players[1].deck[1]
        self.play(g,WILLOW);self.assertEqual({i for i in g.state.players[1].board if g.state.entities[i].card_id==DEMON},{hand,deck})
        self.assertEqual(g.state.entities[hand].zone,Zone.BOARD);self.assertEqual(g.state.entities[deck].zone,Zone.BOARD);self.portable(g)

    def test_original_willow_handles_absent_tribes_and_full_board_with_original_capacity(self):
        g=self.game((WILLOW,DEMON),board=(A,)*6,deck=(DEMON,));self.play(g,WILLOW)
        self.assertEqual(self.entity(g,DEMON).zone,Zone.HAND);self.assertEqual(len(g.state.players[1].deck),1)
        g=self.game((WILLOW,),deck=(A,));self.play(g,WILLOW);self.assertEqual(len(g.state.players[1].board),1)

    def test_original_alabaster_copies_opponent_current_drawn_material_at_one_cost(self):
        g=self.game((PREPARE,),board=(ALABASTER,));self.play(g,PREPARE);self.end(g)
        copied=self.entity(g,A);drawn=self.entity(g,A,2);self.assertNotEqual(copied.id,drawn.id)
        self.assertEqual((copied.attack,copied.health),(drawn.attack,drawn.health));self.assertEqual(copied.origin_entity_id,drawn.id)
        self.assertEqual(quote_cost(g.state,g.registry,copied).amount,1);self.portable(g)

    def test_original_alabaster_does_not_copy_own_draw_or_opponent_burn(self):
        g=self.game((DRAW,),board=(ALABASTER,));source=self.unit(g,ALABASTER).id;self.play(g,DRAW);self.assertFalse(self.created(g,source))
        g=self.game(board=(ALABASTER,),enemy_hand=(A,)*10);source=self.unit(g,ALABASTER).id;self.end(g)
        self.assertFalse(self.created(g,source))

    def test_original_alabaster_copy_notice_wait_restores_once_and_rolls_back_failure(self):
        g=self.game(board=(ALABASTER,COPY_WATCH));self.end(g);before=g.snapshot();g=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.finish(g);self.assertEqual(quote_cost(g.state,g.registry,self.entity(g,A)).amount,1);self.portable(g)

    def test_original_bolvar_own_shield_loss_buffs_one_original_hand_minion(self):
        g=self.game((A,FIREBALL),board=(BOLVAR,));target=self.unit(g,BOLVAR).id;self.power(g,target)
        printed=g.registry.card(A);card=self.entity(g,A);self.assertEqual((card.attack,card.health),(printed.attack+5,printed.health+5))
        self.assertEqual(g.quote_cost(card.id).amount,printed.cost);self.assertEqual(self.entity(g,FIREBALL).card_id,FIREBALL)

    def test_original_bolvar_enemy_shield_loss_does_not_buff_own_hand(self):
        g=self.game((HIT,A),board=(BOLVAR,),enemy=(ALAKIR,));self.play(g,HIT,self.unit(g,ALAKIR,2).id)
        self.assertEqual(self.entity(g,A).attack,g.registry.card(A).attack)

    def test_original_kragwa_recovers_previous_actual_owner_turn_spell_faces_and_multiplicity(self):
        g=self.game((KRAGWA,FIREBALL,FIREBALL));self.play(g,FIREBALL,self.hero(g,2).id);self.play(g,FIREBALL,self.hero(g,2).id)
        self.end(g);self.end(g);source=self.play(g,KRAGWA);created=self.created(g,source)
        self.assertEqual([e.card_id for e in created],[FIREBALL,FIREBALL]);self.assertEqual(len({e.id for e in created}),2);self.portable(g)

    def test_original_halazzi_fills_remaining_hand_slots_with_real_paid_rush_lynxes(self):
        g=self.game((HALAZZI,A),enemy=(LYNX,));source=self.play(g,HALAZZI)
        cards=[g.state.entities[i]for i in g.state.players[1].hand];self.assertEqual(len(cards),10)
        self.assertEqual(sum(c.card_id==LYNX for c in cards),9);self.assertIn(Keyword.RUSH,g.state.entities[source].keywords)
        token=self.play(g,LYNX);g.apply(Attack(1,token,self.unit(g,LYNX,2).id));self.assertEqual(g.state.players[1].mana,25)

    def test_original_siamat_requires_two_distinct_choices_and_restores_real_pending_branch(self):
        g=self.game((SIAMAT,),enemy=(LYNX,LYNX));source=self.play(g,SIAMAT);q=g.state.pending_choice;before=g.snapshot()
        self.assertEqual((q.min_count,q.max_count),(2,2))
        for ids in(('rush',),('rush','rush')):
            with self.assertRaises((ValueError,IllegalAction)):g.apply(SelectChoice(1,q.id,ids))
            self.assertEqual(g.snapshot(),before)
        g=self.portable(g);self.finish(g);self.assertEqual(g.state.entities[source].keywords,{Keyword.RUSH,Keyword.WINDFURY})
        for _ in range(2):g.apply(Attack(1,source,self.unit(g,LYNX,2).id))
        with self.assertRaises(IllegalAction):g.apply(Attack(1,source,self.hero(g,2).id))
        self.portable(g)

    def test_real_standard_host_original_shaku_generates_other_class_card_from_complete_pool(self):
        g=self.game((SHAKU,),real_host=True);source=self.play(g,SHAKU);self.end(g);self.end(g)
        g.apply(Attack(1,source,self.hero(g,2).id));created=self.created(g,source);self.assertEqual(len(created),1)
        meta=g.registry.card(created[0].card_id).metadata;self.assertTrue(meta.collectible)
        self.assertTrue(any(c!=g.state.players[1].hero_class and c.value!='neutral'for c in meta.classes));self.portable(g)

    def test_real_standard_host_original_shaku_generated_notice_wait_restores_attack_and_failure(self):
        g=self.game(board=(SHAKU,COPY_WATCH),real_host=True);source=self.unit(g,SHAKU).id;g.apply(Attack(1,source,self.hero(g,2).id));before=g.snapshot();g=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.finish(g);self.assertEqual(len(self.created(g,source)),1);self.portable(g)
