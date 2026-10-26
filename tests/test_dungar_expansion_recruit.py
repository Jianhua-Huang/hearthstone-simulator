"""Native different-edition recruit through actual physical entries and recovery."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_nefarian_native_dependencies import fixture as base_fixture,FILLER
from hs_sim.cards.dungar_expansion_recruit import CARD,PROFILE,load_batch
from hs_sim.cards.past_summon_prices import PAST_TEN
from hs_sim.engine import (CardDefinition,CardType,Game,PlayerSetup,Registry,ResolutionError,
    Scenario,SnapshotError,SummonQuantitySpec,TriggerSpec,Zone)
from hs_sim.engine.effects import (ChoiceOption,Damage,Destroy,InvokeBehavior,RequestChoice,Transform)
from hs_sim.engine.pools import GenerationContext,PoolDefinition,PoolMember,resolve_candidates
from hs_sim.engine.recruit_expansions import RecruitExpansionProfile,edition
from hs_sim.engine.recruit_summons import validate_record
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.serialization import canonical_hash,SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.zones import AddToDeck
from tools import card_batch as batch

S='k564.'
WATCH,EXTRA,UNKNOWN,NOOP,CLEAR=(S+x for x in ('watch','extra','unknown','noop','clear'))
CORE,LEGACY,CAVERNS='CORE_CS2_179','CS2_182','CORE_CS2_182'
CTX=GenerationContext('k564-native-distinct-printed-expansion','experimental')


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    fmt=base_fixture.__wrapped__('normal',role);r=fmt.registry
    for name in ('constructed.cards','constructed.minions'):
        r.register_pool(replace(r.pool(name,fmt.context),target_id=CTX.target_id,mode=CTX.mode))
    r.register_pool(PoolDefinition('constructed.past.cards','native-dungar-only-test-v1',CTX.target_id,CTX.mode,
        (PoolMember(CARD),),complete=True))
    def fail(c):raise ResolutionError('k564 deliberate resume failure')
    def observe(c):
        roots=c.state.recruit_summon_history
        if not roots or roots[0].spec.expansion_profile!=PROFILE or len(roots[0].rounds)!=1:
            return ()
        first=roots[0].rounds[0]
        if first.selected is None or c.event.target_id!=first.selected.entity_id:
            return ()
        if mode=='terminal':return(Damage(c.state.players[3-c.player_id].hero_id,100,c.source_id),)
        if mode=='unknown':return(AddToDeck(c.player_id,UNKNOWN,position='bottom',source_id=c.source_id),)
        effects=()
        if mode=='mutate':
            effects=(Transform(first.selected.entity_id,CAVERNS),Destroy(roots[0].spec.source_id,c.source_id),
                *(AddToDeck(c.player_id,cid,position='bottom',source_id=c.source_id)
                  for cid in (LEGACY,CAVERNS,'CORE_EX1_007')))
        if mode in ('wait','mutate'):
            return(*effects,RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
                ChoiceOption('fault','Fail',(InvokeBehavior(S+'fail',c.source_id,c.player_id),))),c.source_id))
        return effects
    r.register_behavior(S+'fail',fail);r.register_behavior(S+'watch',observe)
    r.register_behavior(S+'noop',lambda c:())
    r.register_behavior(S+'clear',lambda c:tuple(Destroy(i,c.source_id)for i in c.state.players[c.player_id].board))
    r.register_card(CardDefinition(WATCH,'Entry observer',CardType.WEAPON,durability=20,
        triggers=(TriggerSpec('minion_summoned',S+'watch'),)))
    r.register_card(CardDefinition(EXTRA,'Ordinary quantity source',CardType.MINION,health=8,
        summon_quantities=(SummonQuantitySpec(),)))
    r.register_card(CardDefinition(UNKNOWN,'Unmapped test minion',CardType.MINION,attack=1,health=7))
    r.register_card(CardDefinition(NOOP,'Unmapped test spell',CardType.SPELL,on_play=S+'noop'))
    r.register_card(CardDefinition(CLEAR,'Clear diagnostic board',CardType.SPELL,on_play=S+'clear'))
    r.validate();return replace(fmt,context=CTX)


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items()
        if k not in ('schema_version','events','events_hash','state_hash')})
    return saved


class DungarExpansionRecruitTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:fixture(mode,role).registry)

    def game(self,hand=(CARD,),*,board=(),deck=(CORE,LEGACY,CAVERNS),mode='normal',player=1):
        self.mode=mode
        active=PlayerSetup('HERO_06',hand=hand,board=board,deck=deck,mana=60,max_mana=60,mana_cap=60,
            weapon_card_id=WATCH if mode!='normal'else None)
        other=PlayerSetup('HERO_08',deck=(FILLER,)*5,mana=10,max_mana=10)
        return Game.from_scenario(Scenario((active,other)if player==1 else(other,active),
            active_player=player,seed=564,generation_context=CTX),fixture(mode).registry)

    def sets(self,g,rows):return[edition(g.registry,PROFILE,x.selected.card_id)for x in rows if x.selected]

    def test_complete_original_row_primary_faces_and_full_pinned_printed_inventory(self):
        data=load_batch();rows={r['id']:r for r in batch.read(data['source'])}
        self.assertEqual(batch.sha(data['source']),data['source_sha256'])
        self.assertEqual(data['cards'][0]['record'],rows[CARD])
        for face in data['official_faces']:batch.check_face(rows[CARD],face['face'],face['locale'])
        r=fixture().registry;c=r.card(CARD);profile=r.recruit_expansion_profiles[PROFILE]
        self.assertEqual((c.cost,c.attack,c.health),(10,3,3));self.assertIsNotNone(c.battlecry)
        self.assertEqual(len(profile.editions),23452)
        self.assertEqual(profile.inventory_sha256,data['printed_inventory']['inventory_sha256'])
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])

    def test_actual_payment_moves_three_original_entities_and_skips_their_battlecries(self):
        g=self.game(deck=('WORK_002',CORE,LEGACY));original=set(g.state.players[1].deck)
        source=self.play(g,CARD);parent=g.state.recruit_summon_history[-1]
        self.assertEqual((g.state.players[1].mana,parent.status),(50,'completed'))
        self.assertEqual({x.selected.entity_id for x in parent.rounds},original)
        self.assertEqual(set(g.state.players[1].board),original|{source});self.assertFalse(g.state.players[1].deck)
        self.assertEqual(len(g.state.play_history),1)
        self.assertTrue(all(b.source_id==source for b in g.state.battlecry_history))
        self.assertTrue(all(g.state.entities[i].zone==Zone.BOARD for i in original));self.portable(g)

    def test_one_equal_weight_per_physical_copy_then_original_selected_set_is_excluded(self):
        g=self.game(deck=(CORE,LEGACY,LEGACY,CAVERNS,'CORE_CS2_029'))
        inventory=list(g.state.players[1].deck);rng=Random();rng.setstate(g._rng.getstate())
        pool=[i for i in inventory if g.state.entities[i].kind==CardType.MINION];expected=[];excluded=[];counts=[]
        for _ in range(3):
            counts.append(len(pool))
            chosen=rng.choice(pool);expected.append(chosen)
            excluded.append(edition(g.registry,PROFILE,g.state.entities[chosen].card_id))
            pool=[i for i in pool if edition(g.registry,PROFILE,g.state.entities[i].card_id)not in excluded]
        self.play(g,CARD);root=g.state.recruit_summon_history[-1]
        self.assertEqual([x.selected.entity_id for x in root.rounds],expected)
        self.assertEqual(root.rounds[0].basis.excluded_expansions,())
        self.assertEqual(root.rounds[1].basis.excluded_expansions,tuple(excluded[:1]))
        self.assertEqual(root.rounds[2].basis.excluded_expansions,tuple(excluded[:2]))
        self.assertEqual([len(x.candidates)for x in root.rounds],counts)
        self.assertEqual(g._rng.getstate(),rng.getstate())
        self.assertTrue(all(len(x.basis.inventory)>=len(x.candidates)for x in root.rounds))

    def test_native_ids_with_same_name_use_actual_printed_sets_not_prefix_or_display_name(self):
        g=self.game(deck=('CS2_179',CORE,CAVERNS));self.play(g,CARD)
        root=g.state.recruit_summon_history[-1]
        self.assertEqual(set(self.sets(g,root.rounds)),{1635,1637,1810})
        self.assertEqual(len(root.rounds),3);self.assertEqual(root.status,'completed')

    def test_miniset_and_parent_share_one_group_and_exhaustion_does_not_reroll(self):
        g=self.game(deck=('WORK_002','VAC_412','WORK_002'));self.play(g,CARD)
        root=g.state.recruit_summon_history[-1]
        self.assertEqual((root.status,[x.outcome for x in root.rounds]),('exhausted',['selected','empty']))
        self.assertEqual(self.sets(g,root.rounds),[1905]);self.assertEqual(len(g.state.players[1].deck),2)
        self.assertEqual(root.rounds[-1].rng_before,root.rounds[-1].rng_after);self.portable(g)

    def test_empty_minion_pool_ignores_unknown_spell_edition_and_preserves_rng(self):
        g=self.game(deck=(NOOP,'CORE_CS2_029'));saved_rng=g._rng.getstate();deck=tuple(g.state.players[1].deck)
        self.play(g,CARD);root=g.state.recruit_summon_history[-1]
        self.assertEqual((root.status,root.rounds[0].outcome),('exhausted','empty'))
        self.assertEqual(tuple(g.state.players[1].deck),deck);self.assertEqual(g._rng.getstate(),saved_rng)

    def test_full_board_after_play_stops_before_hidden_query_and_rng(self):
        g=self.game(board=(FILLER,)*6,deck=(UNKNOWN,));saved_rng=g._rng.getstate();deck=tuple(g.state.players[1].deck)
        self.play(g,CARD);root=g.state.recruit_summon_history[-1]
        self.assertEqual((root.status,root.rounds[0].basis),('board_full',None))
        self.assertEqual(g._rng.getstate(),saved_rng);self.assertEqual(tuple(g.state.players[1].deck),deck)
        self.assertEqual(g.state.players[1].mana,50)

    def test_wait_between_entries_restores_original_prefix_and_failed_resume_is_atomic(self):
        g=self.game(mode='wait');self.play(g,CARD);root=g.state.recruit_summon_history[-1]
        self.assertEqual((root.status,len(root.rounds)),('active',1))
        restored=self.portable(g);saved=restored.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate resume failure'):self.choose(restored,'fault')
        self.assertEqual(restored.snapshot(),saved)
        for game in (g,restored):self.choose(game)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.state.recruit_summon_history[-1].status,'completed')
        self.assertEqual(len(set(self.sets(g,g.state.recruit_summon_history[-1].rounds))),3);self.portable(g)

    def test_requery_sees_new_deck_entries_but_keeps_original_set_after_transform_and_source_death(self):
        g=self.game(deck=(CORE,),mode='mutate');source=self.play(g,CARD)
        first=g.state.recruit_summon_history[0].rounds[0]
        self.assertEqual(first.selected.card_id,CORE)
        self.assertEqual(g.state.entities[first.selected.entity_id].card_id,CAVERNS)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        restored=self.portable(g)
        for game in (g,restored):self.choose(game)
        self.assertEqual(g.snapshot(),restored.snapshot());root=g.state.recruit_summon_history[0]
        self.assertEqual(root.status,'completed');self.assertEqual(set(self.sets(g,root.rounds)),{1637,1635,1810})
        self.assertTrue(all(x.card_id!='CORE_EX1_007'for x in root.rounds[1].candidates))
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],['CORE_EX1_007'])
        self.portable(g)

    def test_unmapped_eligible_minion_rejects_explicitly_without_silent_pool_shrink(self):
        g=self.game(deck=(CORE,UNKNOWN,LEGACY));saved=g.snapshot()
        with self.assertRaisesRegex((ResolutionError,UnsupportedDefinitionError),'Unreviewed original recruit printed expansion'):
            self.play(g,CARD)
        self.assertEqual(g.snapshot(),saved)

    def test_unmapped_later_injection_rolls_back_already_moved_first_entry_payment_and_rng(self):
        g=self.game(deck=(CORE,),mode='unknown');saved=g.snapshot()
        with self.assertRaisesRegex((ResolutionError,UnsupportedDefinitionError),'Unreviewed original recruit printed expansion'):
            self.play(g,CARD)
        self.assertEqual(g.snapshot(),saved)

    def test_ordinary_extra_entries_do_not_consume_additional_expansions_or_random_selections(self):
        g=self.game(board=(EXTRA,));original=set(g.state.players[1].deck);self.play(g,CARD)
        parent=g.state.recruit_summon_history[0];children=g.state.card_summon_history
        self.assertEqual((parent.status,len(parent.rounds)),('completed',3))
        self.assertEqual([x.plan.total for x in children],[2,2,2])
        delivered=[[d for d in x.deliveries if d.entity is not None]for x in children]
        self.assertEqual([len(rows)for rows in delivered],[2,2,1])
        self.assertEqual([d.outcome for d in children[-1].deliveries],['delivered','board_full'])
        self.assertEqual({x.deliveries[0].entity.entity_id for x in children},original)
        self.assertTrue(all(len({d.entity.card_id for d in rows})==1 for rows in delivered))
        self.assertEqual(len(set(self.sets(g,parent.rounds))),3);self.portable(g)

    def test_two_native_battlecry_acceptances_have_separate_exclusion_prefixes(self):
        g=self.game(board=('LOE_077',),deck=(CORE,CORE,LEGACY,LEGACY,CAVERNS,CAVERNS));self.play(g,CARD)
        roots=g.state.recruit_summon_history
        self.assertEqual(len(roots),2);self.assertEqual([r.status for r in roots],['completed','board_full'])
        self.assertEqual([r.rounds[0].basis.excluded_expansions for r in roots],[(),()])
        self.assertEqual([len(self.sets(g,r.rounds))for r in roots],[3,2])
        self.assertTrue(all(len(set(self.sets(g,r.rounds)))==len(self.sets(g,r.rounds))for r in roots));self.portable(g)

    def test_later_physical_dungar_does_not_inherit_previous_producer_exclusions(self):
        g=self.game((CARD,CARD,CLEAR),deck=(CORE,CORE,LEGACY,LEGACY,CAVERNS,CAVERNS))
        self.play(g,CARD);self.play(g,CLEAR);self.play(g,CARD)
        roots=g.state.recruit_summon_history
        self.assertEqual([r.status for r in roots],['completed','completed'])
        self.assertEqual([r.rounds[0].basis.excluded_expansions for r in roots],[(),()])
        self.assertEqual([set(self.sets(g,r.rounds))for r in roots],[{1637,1635,1810}]*2)
        self.assertNotEqual(roots[0].spec.source_id,roots[1].spec.source_id)

    def test_terminal_entry_closes_only_the_original_selected_prefix(self):
        g=self.game(mode='terminal');self.play(g,CARD);root=g.state.recruit_summon_history[0]
        self.assertEqual((g.state.status,root.status,len(root.rounds)),('finished','interrupted',1));self.portable(g)

    def test_second_seat_uses_own_deck_without_reading_opponents_expansion_inventory(self):
        g=self.game(player=2);other=tuple(g.state.players[1].deck);self.play(g,CARD,player=2)
        root=g.state.recruit_summon_history[0]
        self.assertEqual((root.spec.player_id,root.status),(2,'completed'))
        self.assertEqual(tuple(g.state.players[1].deck),other)
        self.assertTrue(all(x.basis.player_id==x.basis.owner_id==2 for x in root.rounds))

    def test_rewritten_profile_or_selected_set_prefix_rejects_even_with_recomputed_outer_hash(self):
        g=self.game();self.play(g,CARD);root=g.state.recruit_summon_history[0]
        row=root.rounds[1];wrong=9999 if row.basis.excluded_expansions!=(9999,)else 9998
        bad_row=replace(row,basis=replace(row.basis,excluded_expansions=(wrong,)))
        with self.assertRaisesRegex(ValueError,'selected-set prefix'):
            validate_record(g.state,g.registry,replace(root,rounds=(root.rounds[0],bad_row,*root.rounds[2:])))
        saved=json.loads(json.dumps(g.snapshot()))
        for mode in ('prefix','profile'):
            bad=deepcopy(saved);parent=bad['state']['recruit_summon_history'][0]
            if mode=='prefix':parent['rounds'][1]['basis']['excluded_expansions']=[wrong]
            else:parent['spec']['expansion_profile']='invented.inventory'
            with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture().registry)

    def test_finite_profile_is_immutable_fingerprinted_and_rejects_invalid_or_guessed_shapes(self):
        r=Registry('k564-profile-contract');p=RecruitExpansionProfile('fixture',(('a',1),('b',2)))
        r.register_recruit_expansion_profile(p);fingerprint=r.fingerprint()
        other=Registry('k564-profile-contract');other.register_recruit_expansion_profile(replace(p,editions=(('a',1),('b',3))))
        self.assertNotEqual(fingerprint,other.fingerprint())
        with self.assertRaises(TypeError):p.inventory['a']=3
        with self.assertRaises(ValueError):r.register_recruit_expansion_profile(p)
        for rows in ((('a',True),),(('a',0),),(('b',2),('a',1)),(('a',1),('a',2)),()):
            with self.assertRaises(ValueError):RecruitExpansionProfile('bad',rows)
        g=self.game();self.play(g,CARD);spec=g.state.recruit_summon_history[0].spec
        for changes in (dict(count=2),dict(owner_id=2),dict(zone=Zone.HAND),dict(selection='first'),dict(expansion_profile='')):
            with self.assertRaises(ValueError):replace(spec,**changes)

    def test_private_inventory_exclusions_and_rng_receipts_do_not_enter_player_dtos(self):
        g=self.game(mode='wait');self.play(g,CARD);saved=g.snapshot()
        for player in (1,2):
            view=json.dumps(g.for_player(player).observe())+json.dumps(g.player_events(player))+json.dumps(g.for_player(player).legal_actions())
            for key in ('recruit_summon_history','recruit_selection_accepted','expansion_profile','excluded_expansions','rng_before','inventory_sha256',PROFILE):
                self.assertNotIn('"'+key+'"',view)
        self.assertEqual(g.snapshot(),saved)

    def test_real_frontier_generation_wait_then_set_one_native_play_executes_actual_recruit(self):
        r=fixture().registry;members=resolve_candidates(r,CTX,'constructed.past.cards',PAST_TEN,
            current_class=r.card('CFM_308').metadata.classes[0],source_card_id='GDB_857',player_id=1)
        self.assertEqual([(m.card_id,m.weight)for m in members],[(CARD,1)])
        g=self.game(('GDB_857',));self.play(g,'GDB_857');restored=self.portable(g)
        for game in (g,restored):
            self.choose(game,next(o.id for o in game.state.pending_choice.options if o.card_id==CARD))
            self.play(game,CARD);self.assertEqual(game.state.play_history[-1].cost,1)
            self.assertEqual(game.state.recruit_summon_history[0].status,'completed')
            self.assertEqual(set(self.sets(game,game.state.recruit_summon_history[0].rounds)),{1637,1635,1810})
        self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_new_strict_schema_rejects_old_recruit_basis_without_expansion_fields(self):
        g=self.game();saved=g.snapshot();self.assertEqual(saved['schema_version'],SNAPSHOT_SCHEMA_VERSION)
        saved['schema_version']=595
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,fixture().registry)


if __name__=='__main__':unittest.main()
