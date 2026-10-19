"""Original twenty-card construction, accepted foreign copies and native play."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from random import Random

from hs_sim.cards.azalina_original_deck_card import CARD,load_batch,register_azalina_original_deck_card
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,DeckPolicy,DeckSpec,
    EndTurn,Game,MatchSetup,OpeningHook,PlayCard,PlayerSetup,Rarity,Registry,Scenario,SelectChoice,SnapshotError,Zone)
from hs_sim.engine.construction import DeckValidationError,validate_deck
from hs_sim.engine.effects import (ChoiceOption,DrawToHandLimit,GainArmor,InvokeBehavior,RequestChoice,
    SetStats,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.opening_deck_copies import COUNT,EVENT,is_hook_source
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.zones import CardReference
from hs_sim.engine.sideboards import SideboardSpec

P='azalina.test.'
OWN=tuple(P+'a'+str(i)for i in range(1,31))
ENEMY=tuple(P+'b'+str(i)for i in range(1,31))
PROBE=P+'probe';COIN=P+'coin';HERO=P+'priest';POWER=P+'power'
OTHER_HERO=P+'mage';OTHER_POWER=P+'mage-power';FILL=P+'filler'


@lru_cache(None)
def registry(role='writer',mode='plain'):
    r=Registry('azalina-native-test-'+mode);register_azalina_original_deck_card(r)
    from hs_sim.cards.chef_nethrek_card import register_chef_nethrek_card
    from hs_sim.cards.beatrix_deck_cards import register_beatrix_deck_cards
    register_chef_nethrek_card(r);register_beatrix_deck_cards(r)
    neutral=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON)
    r.register_behavior(P+'noop',lambda c:())
    for hero,power,klass in ((HERO,POWER,CardClass.PRIEST),(OTHER_HERO,OTHER_POWER,CardClass.MAGE),
            (P+'druid',P+'druid-power',CardClass.DRUID),(P+'paladin',P+'paladin-power',CardClass.PALADIN)):
        meta=CardMetadata(False,(klass,),Rarity.NONE)
        r.register_card(CardDefinition(hero,hero,CardType.HERO,health=30,initial_hero_power=power,metadata=meta))
        r.register_card(CardDefinition(power,power,CardType.HERO_POWER,cost=2,on_use=P+'noop',metadata=meta))
    for cid in (*OWN,*ENEMY,FILL):
        meta=replace(neutral,classes=(CardClass.MAGE,))if cid in ENEMY else neutral
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=1,health=2,metadata=meta))
    r.register_card(CardDefinition(P+'two','Two-cost sideboard choice',CardType.MINION,cost=2,attack=1,health=2,metadata=neutral))
    r.register_card(CardDefinition(COIN,COIN,CardType.SPELL,on_play=P+'noop',metadata=replace(neutral,collectible=False)))
    def fail(c):raise ResolutionError('deliberate Azalina opening rollback')
    r.register_behavior(P+'fail',fail)
    def probe(c):
        if not is_hook_source(c.state,c.source_id,c.player_id,PROBE):raise ResolutionError('Probe lost its actual accepted source')
        if mode=='wait':return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
            ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        if mode=='transform':
            eid=c.state.opening.original_entities[1][1]
            return (TransformStoredCard(CardReference.capture(c.state.entities[eid]),FILL,c.source_id),)
        return (GainArmor(c.player_id,1),)
    r.register_behavior(P+'probe',probe)
    r.register_card(CardDefinition(PROBE,PROBE,CardType.MINION,cost=1,attack=1,health=1,
        opening_hooks=(OpeningHook('before_deal',P+'probe'),),metadata=neutral))
    r.register_behavior(P+'summon',lambda c:(Summon(c.player_id,CARD),))
    r.register_card(CardDefinition(P+'summon','Summon',CardType.SPELL,on_play=P+'summon',metadata=neutral))
    r.validate();r.freeze();return r


def setup(*,root=True,mirror=False,first=1,seed=288,probe=False,mode='plain',own=None,enemy=None):
    own=tuple(own)if own is not None else (CARD,*OWN[:19])if root else OWN
    enemy=tuple(enemy)if enemy is not None else (CARD,*OWN[11:30])if mirror else ENEMY
    if probe:enemy=(*enemy[:-1],PROBE)
    r=registry('writer',mode)
    policy=DeckPolicy('azalina-explicit-test','cn37-azalina-experiment','experimental',
        tuple(cid for cid,c in r.cards.items()if c.metadata is not None and c.metadata.collectible),deck_size=30)
    return MatchSetup((DeckSpec(HERO,POWER,CardClass.PRIEST,own),
        DeckSpec(HERO if mirror else OTHER_HERO,POWER if mirror else OTHER_POWER,
            CardClass.PRIEST if mirror else CardClass.MAGE,enemy)),policy,COIN,seed=seed,first_player=first)


class AzalinaOriginalDeckTests(unittest.TestCase):
    def game(self,**kw):
        mode=kw.get('mode','plain');return Game.from_decks(setup(**kw),registry('writer',mode))
    def choose(self,g,ids=()):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,tuple(ids)))
    def finish(self,g):
        while g.state.pending_choice:
            q=g.state.pending_choice
            self.choose(g,()if q.min_count==0 else('ok',))
    def portable(self,g,mode='plain'):
        snap=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(snap,registry('reader',mode))
        self.assertEqual(other.snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),registry('reader',mode)).snapshot(),snap);return other
    def rehash(self,snap):
        snap['events_hash']=canonical_hash(snap['events'])
        snap['state_hash']=canonical_hash({k:v for k,v in snap.items()if k not in ('schema_version','events','events_hash','state_hash')})
        return snap
    def play(self,g,cid,pid=1):
        e=next(g.state.entities[i]for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,e.id,position=len(g.state.players[pid].board)if e.kind==CardType.MINION else None));return e.id

    def test_a01_complete_raw_face_twenty_rule_and_ordinary_battlecry(self):
        r=registry();row=load_batch()['cards'][0]['record'];card=r.card(CARD)
        self.assertEqual((row['cost'],row['attack'],row['health']),(7,7,7))
        self.assertEqual(r.deck_size_rules[CARD].deck_size,20);self.assertEqual(len(load_batch()['official_observations']),2)
        self.assertNotIn('JAIL_430e1',r.cards);self.assertIsNotNone(card.battlecry)

    def test_a02_native_original_twenty_becomes_forty_physical_cards_before_deal(self):
        g=self.game();state=g.state;row,=state.opening.deck_copies
        self.assertEqual(len(state.players[1].original_deck),20)
        self.assertEqual(len(state.opening.original_entities[0]),20)
        self.assertEqual((len(state.players[1].deck),len(state.players[1].hand)),(37,3))
        self.assertEqual((len(row.candidates),len(row.selected),len(row.deliveries)),(30,20,20))
        self.assertEqual(state.entities[state.players[1].hero_id].health,40)
        self.assertEqual(state.entities[state.players[2].hero_id].health,30);self.portable(g)

    def test_a03_each_copied_slot_is_new_owned_and_credits_actual_foreign_original(self):
        g=self.game();row,=g.state.opening.deck_copies
        for origin,fact in zip(row.selected,row.deliveries):
            e=g.state.entities[fact.entity_id]
            self.assertEqual((e.owner,e.controller,e.card_id,e.origin_entity_id),(1,1,origin.card_id,origin.entity_id))
            self.assertIsNotNone(e.copy_origin);self.assertNotEqual(e.id,origin.entity_id)
            self.assertEqual(g.state.entities[origin.entity_id].owner,2)
        self.assertEqual(len(g.state.players[2].deck),26)
        self.assertEqual(len({f.entity_id for f in row.selected}),20);self.assertFalse(g.state.deck_shuffle_history)

    def test_a04_both_originals_freeze_before_mirror_copies_and_do_not_recurse(self):
        g=self.game(mirror=True);rows=g.state.opening.deck_copies
        self.assertEqual(len(rows),2)
        for pid,row in enumerate(rows,1):
            self.assertEqual({f.entity_id for f in row.candidates},set(g.state.opening.original_entities[2-pid]))
            self.assertEqual(len(row.deliveries),20)
            self.assertEqual(sum(f.card_id==CARD for f in row.deliveries),1)
            self.assertEqual(g.state.entities[g.state.players[pid].hero_id].health,40)
        self.finish(g);self.assertEqual(len(g.state.opening.deck_copies),2);self.portable(g)

    def test_a05_second_seat_and_random_first_player_preserve_accepted_players(self):
        config=setup(mirror=True,first=None,seed=12)
        g=Game.from_decks(config,registry());self.assertIn(g.state.opening.first_player,(1,2))
        self.finish(g);self.assertEqual(g.state.active_player,g.state.opening.first_player)
        self.assertEqual(tuple(row.source.controller for row in g.state.opening.deck_copies),(1,2));self.portable(g)

    def test_a06_without_original_root_no_preparation_health_or_new_records(self):
        g=self.game(root=False);self.finish(g)
        self.assertFalse(g.state.opening.deck_copies);self.assertFalse(any(e.kind==EVENT for e in g.events))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].max_health,30);self.portable(g)

    def test_a07_wrong_main_count_or_other_class_is_rejected_before_allocation(self):
        r=registry();config=setup()
        for cards in ((CARD,*OWN[:29]),(CARD,*OWN[:18])):
            deck=replace(config.decks[0],cards=cards)
            report=validate_deck(deck,r,config.policy);self.assertFalse(report.valid)
            self.assertIn('deck_size',[i.code for i in report.issues])
            with self.assertRaises(DeckValidationError):Game.from_decks(replace(config,decks=(deck,config.decks[1])),r)
        wrong=replace(config.decks[0],hero_card_id=OTHER_HERO,hero_power_card_id=OTHER_POWER,card_class=CardClass.MAGE)
        self.assertIn('class',[i.code for i in validate_deck(wrong,r,config.policy).issues])

    def test_a08_actual_full_mulligan_excludes_rejected_physical_ids_and_keeps_copy_proof(self):
        g=self.game();old=tuple(g.state.opening.offered[0]);self.choose(g,tuple(str(i)for i in old))
        self.choose(g);self.assertFalse(set(old)&{f.entity_id for f in g.state.opening.starting_hands[0]})
        self.assertEqual(len(g.state.players[1].hand),4);self.assertEqual(len(g.state.players[1].deck),36)
        self.assertEqual(len(g.state.opening.deck_copies[0].deliveries),20);self.portable(g)

    def test_a09_copied_starting_source_runs_once_before_mulligan(self):
        # A twenty-card opponent guarantees the original probe is copied.
        g=self.game(mirror=True,probe=True)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,1)
        probe_calls=[e for e in g.events if e.kind=='opening_effect'and dict(e.data)['behavior_id']==P+'probe']
        self.assertEqual(len(probe_calls),2);self.portable(g)

    def test_a10_predeal_choice_restores_complete_allocation_before_notifications(self):
        g=self.game(mirror=True,probe=True,mode='wait');self.assertEqual(g.state.opening.stage,'dealing')
        self.assertEqual(len(g.state.opening.deck_copies),2);other=self.portable(g,'wait')
        while g.state.pending_choice:
            q=g.state.pending_choice;keys=()if q.min_count==0 else('ok',)
            self.choose(g,keys);self.choose(other,keys)
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g,'wait')

    def test_a11_failed_predeal_resume_rolls_back_without_resampling_or_reallocation(self):
        g=self.game(mirror=True,probe=True,mode='wait');snap=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,('bad',))
        self.assertEqual(g.snapshot(),snap)
        self.choose(g,('ok',));self.assertEqual(len(g.state.opening.deck_copies[0].selected),20);self.portable(g,'wait')

    def test_a12_later_opening_transform_does_not_rewrite_copied_face_or_original_domain(self):
        g=self.game(mirror=True,probe=True,mode='transform');row=g.state.opening.deck_copies[0]
        origin=row.candidates[1];copy=next(f for a,f in zip(row.selected,row.deliveries)if a.entity_id==origin.entity_id)
        self.assertEqual(g.state.entities[origin.entity_id].card_id,FILL)
        self.assertEqual(g.state.entities[copy.entity_id].card_id,origin.card_id);self.portable(g,'transform')

    def test_a13_native_paid_hand_play_draws_to_capacity_and_does_not_rebuild_deck(self):
        g=Game.from_scenario(Scenario((PlayerSetup(HERO,hand=(CARD,),deck=OWN[:20],mana=7,max_mana=7),PlayerSetup(OTHER_HERO))),registry())
        eid=self.play(g,CARD);self.assertEqual(g.state.players[1].mana,0)
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].max_health),(7,7))
        self.assertEqual((len(g.state.players[1].hand),len(g.state.players[1].deck)),(10,10))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].max_health,30)
        self.assertFalse(any(e.kind==EVENT for e in g.events));self.portable(g)

    def test_a14_native_battlecry_empty_tail_uses_actual_fatigue_without_looping(self):
        g=Game.from_scenario(Scenario((PlayerSetup(HERO,hand=(CARD,*OWN[:8]),deck=(OWN[8],),mana=7,max_mana=7),PlayerSetup(OTHER_HERO))),registry())
        self.play(g,CARD);self.assertEqual(len(g.state.players[1].hand),9)
        self.assertEqual(g.state.players[1].fatigue,1);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,29);self.portable(g)

    def test_a15_natural_summon_has_no_battlecry_construction_or_forty_health(self):
        g=Game.from_scenario(Scenario((PlayerSetup(HERO,hand=(P+'summon',),deck=OWN[:5]),PlayerSetup(OTHER_HERO))),registry())
        self.play(g,P+'summon');self.assertEqual(len(g.state.players[1].board),1)
        self.assertFalse(g.state.players[1].hand);self.assertEqual(len(g.state.players[1].deck),5)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30);self.portable(g)

    def test_a16_initial_copy_receipts_precede_shuffle_and_all_ordinary_hooks(self):
        g=self.game(mirror=True,probe=True)
        copied=[e for e in g.events if e.kind==EVENT];first_created=min(e.sequence for e in g.events if e.kind=='card_created')
        self.assertLess(max(e.sequence for e in copied),first_created)
        self.assertLess(max(e.sequence for e in g.events if e.kind=='card_added_to_deck'),next(e.sequence for e in g.events if e.kind=='game_created'))
        self.assertFalse(g.state.deck_shuffle_history)

    def test_a17_full_rehash_cannot_crop_domain_delivery_or_replace_rng_prefix(self):
        g=self.game()
        for part in ('candidates','deliveries','rng_before'):
            snap=json.loads(json.dumps(g.snapshot()));row=snap['state']['opening']['deck_copies'][0]
            if part=='rng_before':row[part]=snap['rng_state']
            else:row[part]=row[part][:-1]
            with self.assertRaises((ValueError,SnapshotError)):Game.from_snapshot(self.rehash(snap),registry('reader'))

    def test_a18_full_rehash_cannot_drop_preparation_or_borrow_opponents_original_as_copy(self):
        g=self.game(mirror=True)
        for changed in ('drop','original'):
            snap=json.loads(json.dumps(g.snapshot()));rows=snap['state']['opening']['deck_copies']
            if changed=='drop':snap['state']['opening']['deck_copies']=rows[:1]
            else:rows[0]['deliveries'][0]=rows[0]['selected'][0]
            with self.assertRaises((ValueError,SnapshotError)):Game.from_snapshot(self.rehash(snap),registry('reader'))

    def test_a19_original_submitted_provenance_is_separate_from_foreign_prepared_copies(self):
        from hs_sim.engine.play_history import starting_deck_identity
        g=self.game();entities,cards=starting_deck_identity(g.state)
        self.assertEqual(cards[0],(CARD,*OWN[:19]))
        self.assertFalse(set(entities[0])&{f.entity_id for f in g.state.opening.deck_copies[0].deliveries})
        self.assertEqual(tuple(g.snapshot()['generation_context']['starting_decks'][0]),cards[0])

    def test_a20_private_raw_decks_samples_and_receipts_are_never_player_dto(self):
        g=self.game(probe=True,mode='wait')
        for pid in (1,2):
            view=json.dumps(g.observe(pid))+json.dumps(g.player_events(pid))+json.dumps(g.for_player(pid).legal_actions())
            for name in ('deck_copies','candidates','deliveries','rng_before','receipt',EVENT,'original_entities'):
                self.assertNotIn('"'+name+'"',view)
        # No opponent copied identity is exposed before its actual card draw.
        enemy_view=json.dumps(g.observe(2))+json.dumps(g.player_events(2))
        for f in g.state.opening.deck_copies[0].deliveries:
            if f.card_id in ENEMY:self.assertNotIn(f.card_id,enemy_view)

    def test_a21_real_copied_chef_uses_original_qualified_hook_and_existing_condition(self):
        from hs_sim.cards.chef_nethrek_card import ROOT,PROGRAM,PREFIX
        config=setup(seed=next(s for s in range(100)if 0 in Random(s).sample(range(30),20)))
        enemy=DeckSpec(P+'druid',P+'druid-power',CardClass.DRUID,(ROOT,*OWN[:29]))
        g=Game.from_decks(replace(config,decks=(config.decks[0],enemy)),registry())
        row,=g.state.opening.deck_copies
        copied=next(f for f in row.deliveries if f.card_id==ROOT)
        hooks=[e for e in g.events if e.kind=='opening_effect'and dict(e.data)['behavior_id']==PREFIX+'opening']
        self.assertTrue(any(e.source_id==copied.entity_id for e in hooks))
        self.assertFalse([e for e in g.state.players[1].player_effects if e.spec_id==PROGRAM])
        self.assertEqual(len([e for e in g.state.players[2].player_effects if e.spec_id==PROGRAM]),1);self.portable(g)

    def test_a22_real_copied_beatrix_has_no_invented_sideboard_and_original_enemy_still_adds_ten(self):
        from hs_sim.cards.beatrix_deck_cards import ROOT
        config=setup(seed=next(s for s in range(100)if 0 in Random(s).sample(range(30),20)))
        enemy=DeckSpec(P+'paladin',P+'paladin-power',CardClass.PALADIN,(ROOT,*OWN[:29]),
            sideboards=(SideboardSpec(ROOT,(P+'two',)),))
        g=Game.from_decks(replace(config,decks=(config.decks[0],enemy)),registry())
        row,=g.state.opening.deck_copies
        self.assertIn(ROOT,tuple(f.card_id for f in row.deliveries))
        self.assertNotIn(P+'two',tuple(f.card_id for f in row.candidates))
        self.assertFalse(g.state.players[1].sideboards)
        self.assertEqual(tuple(r.player_id for r in g.state.deck_shuffle_history),(2,))
        self.assertEqual(len(g.state.players[2].deck)+len(g.state.players[2].hand),40);self.portable(g)
