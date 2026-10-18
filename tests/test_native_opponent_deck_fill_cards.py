"""Real Ashamane using physical current deck copies and original admission."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json
from random import Random
import unittest

from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_opponent_deck_fill_cards import CARD,load_batch,register_native_opponent_deck_fill_cards
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,
    Registry,Ruleset,Scenario,SelectChoice,TargetSpec,Zone)
from hs_sim.engine.costs import local_cost
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,Destroy,Draw,
    GainArmor,InvokeBehavior,RandomDamage,RequestChoice,Silence)
from hs_sim.engine.errors import ResolutionError,ResolutionLimitExceeded,SnapshotError
from hs_sim.engine.hand_capacity import SetHandCapacity
from hs_sim.engine.model import CostAuraSpec,CostSpec,LimitedTriggerSpec,TriggerSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import AddToDeck,CardReference,CopyMatching,ModifyStoredCost
from hs_sim.targets import canonical_digest

P='k194.';HERO=P+'hero';A=P+'minion';B=P+'spell';LOW=P+'low';LOC=P+'location';WEAPON=P+'weapon'
WATCH=P+'watch';OWN_AURA=P+'own_aura';ENEMY_AURA=P+'enemy_aura'


@lru_cache(maxsize=None)
def registry(mode=None):
    r=Registry('k194-physical-deck-fill-'+str(mode));register_native_opponent_deck_fill_cards(r)
    r.register_behavior(P+'noop',lambda c:())
    r.register_behavior(P+'battlecry',lambda c:(GainArmor(c.player_id,99),))
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=80))
    r.register_card(CardDefinition(A,A,CardType.MINION,cost=5,attack=2,health=5,battlecry=P+'battlecry'))
    for cid,cost in((B,7),(LOW,2)):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=P+'noop'))
    r.register_card(CardDefinition(LOC,LOC,CardType.LOCATION,cost=2,durability=2,on_use=P+'noop'))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,cost=4,attack=2,durability=2))
    for cid,delta in((OWN_AURA,-1),(ENEMY_AURA,-4)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=20,
            cost_auras=(CostAuraSpec(CostSpec(delta=delta,card_types=(CardType.MINION,))),)))
    def prepare(c):
        entity=c.state.entities[c.state.players[2].deck[0]]
        return(ModifyStoredCost(CardReference.capture(entity),CostSpec(delta=-1),c.source_id),)
    bodies={
        'prepare':prepare,
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'invalid_cost':lambda c:(CopyMatching(c.player_id,2,Zone.DECK,count=1,source_id=c.source_id,
            cost=CostSpec(delta=-3,card_types=(CardType.MINION,))),),
        'fail':lambda c:(_ for _ in()).throw(ResolutionError('K194 deliberate failure')),
    }
    for name,body in bodies.items():
        r.register_behavior(P+name,body)
        if name=='fail':continue
        fields={'targeting':TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))}if name in('kill','silence')else{}
        r.register_card(CardDefinition(P+name,P+name,CardType.SPELL,on_play=P+name,**fields))
    if mode not in(None,'auras'):
        event='minion_summoned'if mode=='before_full'else'card_created'if mode=='created'else'card_added_to_hand'
        def eligible(c):
            source=c.state.entities.get(c.event.source_id)
            return source is not None and source.card_id==CARD and c.event.player_id==c.player_id
        def watch(c):
            if not eligible(c):return ()
            if mode=='before_full':return(AddToHand(c.player_id,A,c.source_id),)
            entity=c.state.entities[c.event.target_id]
            if mode=='created':return(GainArmor(c.player_id,max(0,local_cost(entity)[0])),)
            count=sum(c.state.entities[i].origin_entity_id is not None for i in c.state.players[c.player_id].hand)
            if count!=1:return ()
            if mode=='shrink':return(SetHandCapacity(c.player_id,1),)
            if mode=='expand':return(SetHandCapacity(c.player_id,7),)
            if mode=='draw_source':return(Draw(2,source_id=c.source_id),)
            if mode=='add_source':return(AddToDeck(2,B,'top',c.source_id),)
            if mode=='change_source':
                original=c.state.entities[c.state.players[2].deck[0]]
                return(ModifyStoredCost(CardReference.capture(original),CostSpec(delta=-2),c.source_id),)
            if mode=='failure':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            options=(ChoiceOption('ok','Continue'),ChoiceOption('kill','Remove original source',(Destroy(c.event.source_id,c.source_id),)),
                ChoiceOption('give','Transfer original source',(ChangeControl(c.event.source_id,2),)),
                ChoiceOption('fail','Rollback',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(P+'fail',c.source_id,c.player_id))))
            return(RequestChoice(c.player_id,options,c.source_id),)
        r.register_trigger_condition(P+'eligible',eligible);r.register_behavior(P+'watch',watch)
        fields={'triggers':(TriggerSpec(event,P+'watch'),)}if mode=='created'else{
            'limited_triggers':(LimitedTriggerSpec(event,P+'watch',condition_id=P+'eligible'),)}
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,**fields))
    r.validate();return r


class NativeOpponentDeckFillTests(unittest.TestCase):
    def game(self,hand=(CARD,),deck=(A,),mode=None,cap=4,board=(),rules=None):
        self.mode=mode
        if mode=='auras':board=(*board,OWN_AURA)
        elif mode:board=(*board,WATCH)
        enemy=(ENEMY_AURA,)if mode=='auras'else()
        return Game.from_scenario(Scenario((
            PlayerSetup(HERO,hand=hand,board=board,deck=(LOW,)*12,mana=100,max_mana=100,mana_cap=100,hand_cap=cap),
            PlayerSetup(HERO,board=enemy,deck=deck,mana=100,max_mana=100,mana_cap=100)),seed=194),registry(mode),ruleset=rules)

    def play(self,g,cid=CARD,target=None):
        p=g.state.active_player;eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,eid,target));return eid

    def copies(self,g,p=1):return[g.state.entities[i]for i in g.state.players[p].hand if g.state.entities[i].origin_entity_id is not None]

    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def random(self,g):
        s=g.snapshot()['rng_state'];rng=Random();rng.setstate((s[0],tuple(s[1]),s[2]));return rng

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));reader=registry.__wrapped__(self.mode)
        self.assertIsNot(reader,g.registry)
        self.assertEqual(Game.from_snapshot(deepcopy(saved),reader).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),reader).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for key in('origin_entity_id','CardReference','CopyMatching','FillHandWithDeckCopies','resolution_frame','rng_state'):
                self.assertNotIn('"'+key+'"',public)

    def test_complete_native_beast_legendary_source_and_two_primary_faces(self):
        d=load_batch();raw=d['cards'][0]['record'];card=registry().card(CARD)
        self.assertEqual(canonical_digest(raw),d['cards'][0]['record_sha256'])
        self.assertEqual(card.metadata,metadata_from_record(raw));self.assertEqual((card.cost,card.attack,card.health),(9,7,7))
        self.assertEqual(card.metadata.tribes,('beast',));self.assertEqual(raw['tags']['4065'],1)
        self.assertEqual(len(d['official_observations']),2);self.assertFalse(d['formal_pool_complete']or d['cn_calibrated'])

    def test_real_battlecry_fills_current_capacity_pays_once_and_preserves_original_deck(self):
        g=self.game(cap=4);originals={i:asdict(g.state.entities[i])for i in g.state.players[2].deck};source=self.play(g)
        self.assertEqual(len(self.copies(g)),4);self.assertEqual(g.state.players[1].mana,91)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(7,7))
        self.assertEqual({i:asdict(g.state.entities[i])for i in g.state.players[2].deck},originals)
        self.assertEqual([g.quote_cost(e.id).amount for e in self.copies(g)],[2]*4)
        self.assertTrue(all(e.owner==e.controller==1 for e in self.copies(g)))
        self.assertFalse(g.state.cast_history);self.portable(g)

    def test_sampling_keeps_physical_duplicate_weights_and_uses_replacement(self):
        g=self.game(deck=(A,A,B),cap=7);basis=list(g.state.players[2].deck);rng=self.random(g)
        expected=[rng.choice(basis)for _ in range(7)];self.play(g)
        self.assertEqual([e.origin_entity_id for e in self.copies(g)],expected)
        self.assertEqual(g.state.players[2].deck,basis);self.portable(g)

    def test_preexisting_same_face_hand_card_does_not_receive_copy_discount(self):
        g=self.game((CARD,A),cap=4);old=g.state.players[1].hand[1];self.play(g)
        self.assertEqual(g.quote_cost(old).amount,5)
        self.assertEqual([g.quote_cost(e.id).amount for e in self.copies(g)],[2]*3);self.portable(g)

    def test_current_source_local_cost_is_copied_then_new_discount_installed(self):
        g=self.game((P+'prepare',CARD));self.play(g,P+'prepare');original=g.state.players[2].deck[0]
        self.assertEqual(local_cost(g.state.entities[original])[0],4);before=asdict(g.state.entities[original]);self.play(g)
        self.assertEqual([g.quote_cost(e.id).amount for e in self.copies(g)],[1]*4)
        self.assertEqual(asdict(g.state.entities[original]),before);self.portable(g)

    def test_new_owner_aura_applies_without_copying_opponent_aura_price(self):
        g=self.game(mode='auras');self.play(g)
        self.assertEqual([g.quote_cost(e.id).amount for e in self.copies(g)],[1]*4);self.portable(g)

    def test_discount_is_installed_before_first_created_notification(self):
        g=self.game(mode='created',cap=3);self.play(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,6)
        self.assertEqual([g.quote_cost(e.id).amount for e in self.copies(g)],[2]*3);self.portable(g)

    def test_copies_of_all_ordinary_hand_card_types_use_the_same_delivery(self):
        for cid,cost in((A,2),(B,4),(LOW,0),(LOC,0),(WEAPON,1)):
            with self.subTest(cid=cid):
                g=self.game(deck=(cid,),cap=2);self.play(g)
                self.assertEqual([e.card_id for e in self.copies(g)],[cid]*2)
                self.assertEqual([g.quote_cost(e.id).amount for e in self.copies(g)],[cost]*2);self.portable(g)

    def test_copy_creation_does_not_trigger_source_minion_battlecry_until_played(self):
        g=self.game(cap=2);self.play(g);hero=g.state.players[1].hero_id
        self.assertEqual(g.state.entities[hero].armor,0);self.play(g,A)
        self.assertEqual(g.state.entities[hero].armor,99);self.portable(g)

    def test_permanent_discount_survives_source_silence_death_and_turn_change(self):
        g=self.game((CARD,P+'silence',P+'kill'),cap=5);source=self.play(g)
        self.play(g,P+'silence',source);self.play(g,P+'kill',source)
        g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertTrue(self.copies(g));self.assertTrue(all(g.quote_cost(e.id).amount==2 for e in self.copies(g)));self.portable(g)

    def test_player_override_and_default_capacity_are_both_respected(self):
        for cap,expected in((3,3),(12,12),(None,10)):
            with self.subTest(cap=cap):
                g=self.game(cap=cap);self.play(g);self.assertEqual(len(g.state.players[1].hand),expected)

    def test_empty_opponent_deck_does_not_draw_or_fatigue_either_player(self):
        g=self.game(deck=());fatigue=[g.state.players[p].fatigue for p in(1,2)];rng=g.snapshot()['rng_state'];self.play(g)
        self.assertFalse(g.state.players[1].hand);self.assertEqual([g.state.players[p].fatigue for p in(1,2)],fatigue)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertFalse(any(e.kind=='card_drawn'for e in g.events));self.portable(g)

    def test_hand_filled_by_entry_reaction_has_no_remaining_copy_or_rng(self):
        g=self.game((CARD,A,A),cap=3,mode='before_full');rng=g.snapshot()['rng_state'];self.play(g)
        self.assertEqual(len(g.state.players[1].hand),3);self.assertFalse(self.copies(g))
        self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)

    def test_shrunk_hand_capacity_burns_owed_copies_without_refill_loop(self):
        g=self.game(cap=4,mode='shrink');source=self.play(g)
        self.assertEqual(len(self.copies(g)),1)
        burned=[e for e in g.events if e.kind=='card_burned'and e.source_id==source]
        self.assertEqual(len(burned),3);self.assertEqual(len(g.state.players[2].deck),1);self.portable(g)

    def test_expanded_capacity_does_not_change_original_finite_slot_quote(self):
        g=self.game(cap=3,mode='expand');self.play(g)
        self.assertEqual((g.state.players[1].hand_cap,len(g.state.players[1].hand)),(7,3));self.portable(g)

    def test_later_copy_requeries_deck_after_previous_copy_draws_original_top(self):
        g=self.game(deck=(A,B),cap=3,mode='draw_source');basis=list(g.state.players[2].deck)
        first=self.random(g).choice(basis);self.play(g)
        self.assertEqual([e.origin_entity_id for e in self.copies(g)],[first,basis[1],basis[1]])
        self.assertEqual(g.state.players[2].hand,[basis[0]]);self.assertEqual(g.state.players[2].deck,[basis[1]]);self.portable(g)

    def test_later_copy_sees_new_physical_card_added_by_previous_reaction(self):
        g=self.game(deck=(A,),cap=4,mode='add_source');rng=self.random(g);rng.choice((0,))
        self.play(g);source_ids=list(g.state.players[2].deck)
        expected=[g.state.entities[rng.choice(source_ids)].card_id for _ in range(3)]
        self.assertEqual([e.card_id for e in self.copies(g)],[A,*expected]);self.portable(g)

    def test_later_copy_uses_current_source_material_changed_by_first_reaction(self):
        g=self.game(cap=3,mode='change_source');self.play(g)
        self.assertEqual([g.quote_cost(e.id).amount for e in self.copies(g)],[2,0,0]);self.portable(g)

    def test_creation_wait_restores_chosen_copy_cost_and_unexecuted_tail(self):
        g=self.game(mode='wait',cap=3);self.play(g)
        self.assertEqual(len(self.copies(g)),1);self.assertEqual(g.quote_cost(self.copies(g)[0].id).amount,2)
        self.portable(g);self.choose(g);self.assertEqual(len(self.copies(g)),3);self.portable(g)

    def test_source_retirement_or_transfer_does_not_redirect_accepted_fill(self):
        for key in('kill','give'):
            with self.subTest(key=key):
                g=self.game(mode='wait',cap=3);source=self.play(g);self.choose(g,key)
                self.assertEqual(len(self.copies(g)),3);self.assertFalse(g.state.players[2].hand)
                self.assertTrue(all(e.controller==1 for e in self.copies(g)))
                self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD if key=='kill'else Zone.BOARD);self.portable(g)

    def test_failed_choice_rolls_back_rng_information_and_owed_tail(self):
        g=self.game(mode='wait',cap=3);self.play(g);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K194 deliberate'):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.portable(g);self.choose(g);self.portable(g)

    def test_original_battlecry_failure_restores_payment_entities_and_source_deck(self):
        g=self.game(mode='failure');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K194 deliberate'):self.play(g)
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_invalid_creation_cost_does_not_crop_candidate_domain_or_spend_rng(self):
        g=self.game((P+'invalid_cost',),deck=(A,B));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Cost does not match'):self.play(g,P+'invalid_cost')
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_fill_budget_rejection_restores_real_play_without_partial_copies(self):
        g=self.game(cap=50,rules=Ruleset(max_resolution_steps=40));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionLimitExceeded,'Deck-copy fill exceeds'):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_actor_two_copies_from_player_one_and_owns_new_local_costs(self):
        self.mode=None
        g=Game.from_scenario(Scenario((PlayerSetup(HERO,deck=(A,),mana=100,max_mana=100,mana_cap=100),
            PlayerSetup(HERO,hand=(CARD,),deck=(LOW,)*10,mana=100,max_mana=100,mana_cap=100,hand_cap=3)),
            active_player=2,seed=194),registry())
        originals=list(g.state.players[1].deck);self.play(g)
        self.assertEqual(g.state.players[1].deck,originals);self.assertEqual(len(self.copies(g,2)),3)
        self.assertTrue(all(e.owner==e.controller==2 for e in self.copies(g,2)))
        self.assertEqual([g.quote_cost(e.id).amount for e in self.copies(g,2)],[2]*3);self.portable(g)

    def test_previous_snapshot_schema_is_explicitly_rejected(self):
        g=self.game();saved=g.snapshot();saved['schema_version']=396
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())


if __name__=='__main__':unittest.main()
