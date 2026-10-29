"""Real other-class Secret CASTs and printed copies of physical turn plays."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json,unittest
from unittest.mock import patch
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from tools import card_batch as batch
from hs_sim.cards import perjury_plagiarize as native
from hs_sim.cards.archaedas_card import WEAPON as CARVED_WEAPON,register_archaedas_card
from hs_sim.engine import EndTurn,Game,PlayCard,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.actions import UseHeroPower
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.carved_spells import weapon_material
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.effects import (AddCostModifier,AddToHand,ChoiceOption,GainArmor,InvokeBehavior,
    RandomDamage,RequestChoice,ReturnToHand,Summon,Transform)
from hs_sim.engine.model import CardClass,CardDefinition,CardType,CostSpec,Keyword,SecretSpec,TriggerSpec,Zone
from hs_sim.engine.pools import DiscoverFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery,resolve_candidates
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.spent_spells import ReturnSpentSpell
from hs_sim.engine.zones import CardReference,CopyCard,MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format

PERJURY,PLAGIARIZE=native.LEAVES
P='k644.'
M,OTHER,S,WPN,LOC,HERO,AUTO,BOUNCE,PREP,FILL,OP,WATCH,FAIL=(P+x for x in
    ('minion','other','spell','weapon','location','hero','auto','bounce','prep','fill','op','watch','fail'))
A,B,C,D=(P+'secret'+str(i)for i in range(4))


def context(mode):return GenerationContext('k644-explicit-'+mode,'experimental')


def prompt(c):
    return RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(
        RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),
        source_id=c.source_id,prompt='K644 original reaction')


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=opening_registry();native.register_perjury_plagiarize(r)
    if mode=='weapon_carve':register_archaedas_card(r)
    r.register_card(CardDefinition('rogue.hero','Rogue',CardType.HERO,health=30,metadata=metadata(CardClass.ROGUE,collectible=False)))
    def fail(c):raise ValueError('K644 deliberate failure')
    r.register_behavior(FAIL,fail);r.register_behavior(S,lambda c:(GainArmor(c.player_id,1),))
    r.register_behavior(M,lambda c:(Transform(c.source_id,OTHER),)if mode=='minion_transform'else())
    for cid,fields in ((M,dict(cost=1,attack=2,health=4,battlecry=M)),(OTHER,dict(cost=2,attack=5,health=6))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,metadata=metadata(),**fields))
    r.register_card(CardDefinition(WPN,WPN,CardType.WEAPON,cost=1,attack=2,durability=2,metadata=metadata()))
    r.register_card(CardDefinition(LOC,LOC,CardType.LOCATION,cost=1,durability=2,on_use=S,metadata=metadata()))
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,cost=1,health=30,hero_card=True,initial_hero_power='mage.power',metadata=metadata(CardClass.MAGE)))
    def bounce(c):
        target=next((i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id in(M,OTHER)),None)
        return ()if target is None else(ReturnToHand(target),)
    r.register_behavior(BOUNCE,bounce)
    r.register_behavior(AUTO,lambda c:(CastSpell(c.player_id,S,c.source_id),Summon(c.player_id,M)))
    r.register_behavior(PREP,lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-2),uses_remaining=1,source_id=c.source_id),))
    r.register_behavior(FILL,lambda c:tuple(AddToHand(c.player_id,M,c.source_id)for _ in range(10)))
    def op(c):
        if mode=='weapon_carve':return(AddToHand(c.player_id,CARVED_WEAPON,c.source_id,carved_spell_id=S),)
        if mode=='source_change':
            row=next(row for row in c.state.play_history if row.card_id==S and row.player_id==2)
            entity=c.state.entities[row.source_id]
            if entity.zone==Zone.GRAVEYARD:return(ReturnSpentSpell(SourceAllocationFact.capture(c.state,entity),c.player_id),)
            ref=CardReference.capture(entity)
            return(MoveCard(ref,1,Zone.DECK,'top',source_id=c.source_id),)if ref.zone==Zone.HAND else(TransformStoredCard(ref,M,c.source_id),)
        if mode=='copy_forged':
            face=c.state.play_history[-2].played_face
            return(CopyCard(replace(face,play_id=len(c.state.play_history)+1),1,mode='base',source_id=c.source_id),)
        return ()
    r.register_behavior(OP,op)
    for cid,cost in ((S,3),(AUTO,1),(BOUNCE,0),(PREP,0),(FILL,0),(OP,0)):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=cid,metadata=metadata()))
    for cid,cls in ((A,CardClass.MAGE),(B,CardClass.MAGE),(C,CardClass.HUNTER),(D,CardClass.ROGUE)):
        r.register_behavior(cid,lambda c,cid=cid:(CounterSpell(c.window.id),)if mode=='counter'and cid==A else(GainArmor(c.player_id,2),))
        r.register_secret_condition(cid,lambda c:True)
        card=CardDefinition(cid,cid,CardType.SPELL,keywords=(Keyword.SECRET,),
            secret=SecretSpec(cid,('card_committed',),cid,cid),metadata=metadata(cls))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    members=()if mode=='empty'else tuple(PoolMember(cid,weight=3 if cid==A else 1)for cid in(A,B,C,D))
    if mode=='unknown':
        r.register_pool_card(PoolCard(P+'unknown',CardType.SPELL,1,metadata(CardClass.MAGE),keywords=(Keyword.SECRET,)))
        members=(*members,PoolMember(P+'unknown'))
    r.register_pool(PoolDefinition('constructed.cards','k644-complete-diagnostic-'+mode,context(mode).target_id,
        context(mode).mode,members,complete=True))
    def watch(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None:return ()
        is_reveal=c.event.kind=='secret_revealed'and source.card_id in native.LEAVES
        is_copy=c.event.kind=='card_added_to_hand'and source.card_id==PLAGIARIZE
        is_cast=c.event.kind=='spell_cast_accepted'and source.card_id in(A,B,C,D)
        if is_reveal and mode=='end_fail':return(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))
        if (is_reveal and mode=='reveal_wait')or(is_copy and mode=='copy_wait')or(is_cast and mode=='cast_wait'):
            return(prompt(c),)
        return ()
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=10,metadata=metadata(),triggers=tuple(
        TriggerSpec(event,WATCH)for event in('secret_revealed','card_added_to_hand','spell_cast_accepted'))))
    r.validate();return r


@lru_cache(None)
def host():return build_cn37_local_pool_format()


class PerjuryPlagiarizeTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'
    def game(self,secret=PLAGIARIZE,*,mode='normal',owner_hand=None,enemy_hand=None,watch=False,hero='rogue.hero',hand_cap=None):
        self.mode=mode
        g=Game.from_scenario(Scenario((PlayerSetup(hero,hand=(secret,)if owner_hand is None else owner_hand,
            deck=(M,)*12,mana=10,max_mana=10,board=(WATCH,)if watch else(),hand_cap=hand_cap),
            PlayerSetup('warrior.hero',hand=(S,M,WPN,LOC,HERO,AUTO,BOUNCE,PREP)if enemy_hand is None else enemy_hand,
                deck=(M,)*12,mana=10,max_mana=10,hero_power_card_id='warrior.power')),
            seed=644,generation_context=None if mode=='unbound'else context(mode)),registry(mode))
        self.play(g,secret)
        if mode in('existing','counter'):self.play(g,A)
        if mode=='hero_change':self.play(g,HERO)
        g.apply(EndTurn(1));return g
    def finish(self,g):g.apply(EndTurn(2));return g
    def pick(self,g,cid):self.choose(g,next(o.id for o in g.state.pending_choice.options if o.card_id==cid))
    def copies(self,g,zone=Zone.HAND):
        return tuple(e for e in g.state.entities.values()if e.owner==1 and e.copy_origin is not None and(zone is None or e.zone==zone))
    def secrets(self,g):return tuple(g.state.entities[i].card_id for i in g.state.players[1].secrets)

    def test_two_full_records_four_official_faces_and_original_turn_policies(self):
        d=native.load_batch();rows={x['record']['id']:x['record']for x in d['dependencies']}
        for o in d['official_observations']:batch.check_face(rows[o['card_id']],o['face'],o['locale'])
        r=registry();self.assertEqual(r.card(PERJURY).secret.turn,'owner');self.assertEqual(r.card(PLAGIARIZE).secret.turn,'opponent')
        self.assertFalse(d['new_standard_roots']);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])

    def test_invalid_final_source_does_not_partially_register(self):
        r=opening_registry();before=r.fingerprint();d=deepcopy(native.load_batch());d['dependencies'][-1]['record']['cost']=-1
        with patch.object(native,'load_batch',return_value=d),self.assertRaises(ValueError):native.register_perjury_plagiarize(r)
        self.assertEqual(r.fingerprint(),before)

    def test_perjury_waits_for_owner_start_and_casts_selected_other_class_secret_free(self):
        g=self.game(PERJURY);self.assertFalse(g.state.pending_choice);self.assertEqual(self.secrets(g),(PERJURY,))
        source=g.state.players[1].secrets[0];self.finish(g)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},{A,B,C});self.pick(g,A)
        cast=g.state.cast_history[-1];self.assertEqual((cast.origin,cast.caster_id,cast.card_id),('effect',source,A))
        self.assertEqual(self.secrets(g),(A,));self.assertEqual(g.state.players[1].mana,10)
        self.assertFalse(any(e.kind=='card_added_to_hand'and e.target_id==cast.source_id for e in g.events));self.portable(g)

    def test_perjury_uses_current_hero_class_with_complete_other_class_weights(self):
        g=self.game(PERJURY,mode='hero_change',owner_hand=(PERJURY,HERO));self.finish(g)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},{C,D})
        candidates=resolve_candidates(registry(),context('normal'),'constructed.cards',native.SECRETS,current_class=CardClass.ROGUE)
        self.assertEqual([(x.card_id,x.weight)for x in candidates],[(A,3),(B,1),(C,1)])
        self.pick(g,D);self.assertEqual(self.secrets(g),(D,))

    def test_perjury_keeps_already_active_secret_in_offer(self):
        g=self.game(PERJURY,mode='existing',owner_hand=(PERJURY,A));original=self.entity(g,A,zone='secrets').id
        self.finish(g);self.assertIn(A,{o.card_id for o in g.state.pending_choice.options});self.pick(g,A)
        self.assertEqual(g.state.players[1].secrets,[original]);self.assertEqual(g.state.cast_history[-1].card_id,A)
        self.assertNotEqual(g.state.cast_history[-1].source_id,original)

    def test_perjury_empty_complete_domain_consumes_no_rng_and_has_no_menu(self):
        g=self.game(PERJURY,mode='empty');before=g.snapshot()['rng_state'];self.finish(g)
        self.assertIsNone(g.state.pending_choice);self.assertFalse(self.secrets(g));self.assertEqual(g.snapshot()['rng_state'],before)

    def test_perjury_unknown_or_unbound_domain_fails_atomically_without_cropping(self):
        for mode in('unknown','unbound'):
            g=self.game(PERJURY,mode=mode);before=g.snapshot()
            with self.assertRaises(ResolutionError):self.finish(g)
            self.assertEqual(g.snapshot(),before)

    def test_perjury_full_hand_does_not_block_direct_cast(self):
        g=self.game(PERJURY,owner_hand=(PERJURY,)+(M,)*8,hand_cap=9);self.finish(g);self.pick(g,B)
        self.assertEqual(self.secrets(g),(B,));self.assertEqual(len(g.state.players[1].hand),9)

    def test_perjury_original_menu_and_selected_cast_wait_restore_and_replay(self):
        g=self.game(PERJURY,mode='cast_wait',watch=True);self.finish(g);g=self.portable(g);self.pick(g,C)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.choose(g);self.assertEqual(self.secrets(g),(C,));self.portable(g)

    def test_perjury_reveal_wait_preserves_original_source_and_class_query(self):
        g=self.game(PERJURY,mode='reveal_wait',watch=True);self.finish(g);g=self.portable(g);self.choose(g)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},{A,B,C});self.pick(g,B);self.portable(g)

    def test_perjury_selected_reaction_failure_rolls_back_rng_menu_and_allocators(self):
        g=self.game(PERJURY,mode='cast_wait',watch=True);self.finish(g);self.pick(g,A);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(self.secrets(g),(A,))

    def test_direct_cast_finite_policy_rejects_extra_other_class_discoveries_or_hand_boons(self):
        fields=dict(player_id=1,pool_id='constructed.cards',query=native.SECRETS,source_id=1,destination='cast')
        DiscoverFromPool(**fields)
        for delta in(dict(discoveries=2),dict(cost=CostSpec(delta=-1)),dict(query=PoolQuery(class_mode='other')),
                dict(unselected_to_hand=True),dict(replacement=False)):
            with self.assertRaises(ValueError):DiscoverFromPool(**dict(fields,**delta))

    def test_plagiarize_copies_all_five_physical_card_kinds_in_original_order(self):
        g=self.game()
        for cid in(S,M,WPN,LOC,HERO):self.play(g,cid,player=2)
        original=tuple(row.source_id for row in g.state.play_history if row.player_id==2);self.finish(g)
        copies=self.copies(g);self.assertEqual(tuple(e.card_id for e in copies),(S,M,WPN,LOC,HERO))
        self.assertEqual(tuple(e.origin_entity_id for e in copies),original)
        self.assertTrue(all(e.copy_origin.controller==2 for e in copies));self.portable(g)

    def test_plagiarize_uses_base_cost_without_preserving_original_discount(self):
        g=self.game();self.play(g,PREP,player=2);self.play(g,S,player=2)
        self.assertEqual(g.state.play_history[-1].cost,1);self.finish(g)
        self.assertEqual(tuple(e.card_id for e in self.copies(g)),(PREP,S));self.assertEqual(self.copies(g)[1].base_cost,3)

    def test_plagiarize_freezes_original_minion_face_before_battlecry_transformation(self):
        g=self.game(mode='minion_transform');original=self.play(g,M,player=2);self.assertEqual(g.state.entities[original].card_id,OTHER)
        self.finish(g);copy=self.copies(g)[0];self.assertEqual((copy.card_id,copy.attack,copy.health),(M,2,4));self.portable(g)

    def test_plagiarize_preserves_repeated_plays_of_same_physical_minion(self):
        g=self.game();ident=self.play(g,M,player=2);self.play(g,BOUNCE,player=2);g.apply(PlayCard(2,ident))
        self.finish(g);self.assertEqual(tuple(e.card_id for e in self.copies(g)),(M,BOUNCE,M))
        self.assertEqual([e.origin_entity_id for e in self.copies(g)if e.card_id==M],[ident,ident])

    def test_plagiarize_includes_countered_physical_play_without_running_its_body(self):
        g=self.game(mode='counter',owner_hand=(PLAGIARIZE,A));self.play(g,S,player=2)
        self.assertTrue(g.state.play_history[-1].countered);self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,0)
        self.finish(g);self.assertEqual(tuple(e.card_id for e in self.copies(g)),(S,));self.portable(g)

    def test_plagiarize_nonminion_identity_survives_later_move_transform_and_control_change(self):
        g=self.game(mode='source_change',enemy_hand=(S,OP,OP,OP));source=self.play(g,S,player=2)
        for _ in range(3):self.play(g,OP,player=2)
        self.assertEqual((g.state.entities[source].card_id,g.state.entities[source].controller),(M,1))
        self.finish(g);self.assertEqual(tuple(e.card_id for e in self.copies(g)),(S,OP,OP,OP))
        origin=self.copies(g)[0].copy_origin;self.assertEqual((origin.entity_id,origin.card_id,origin.owner,origin.controller),(source,S,2,2))
        self.portable(g)

    def test_plagiarize_real_carved_weapon_retains_original_native_spell_and_intrinsic_cost(self):
        g=self.game(mode='weapon_carve',enemy_hand=(OP,));self.play(g,OP,player=2);self.play(g,CARVED_WEAPON,player=2)
        self.finish(g);weapon=next(e for e in self.copies(g)if e.card_id==CARVED_WEAPON)
        self.assertEqual((weapon.base_cost,weapon.attack,weapon.durability),(3,3,3));self.assertEqual(weapon_material(weapon)[1],S)
        self.portable(g)

    def test_plagiarize_excludes_generated_casts_summons_and_powers(self):
        g=self.game();self.play(g,AUTO,player=2);g.apply(UseHeroPower(2,g.state.players[2].hero_power_id));self.finish(g)
        self.assertEqual(tuple(e.card_id for e in self.copies(g)),(AUTO,));self.assertGreater(len(g.state.cast_history),2)

    def test_plagiarize_empty_opponent_turn_keeps_secret_for_later_actual_plays(self):
        g=self.game();g.apply(UseHeroPower(2,g.state.players[2].hero_power_id));self.finish(g)
        self.assertEqual(self.secrets(g),(PLAGIARIZE,));g.apply(EndTurn(1));self.play(g,S,player=2);self.finish(g)
        self.assertEqual(tuple(e.card_id for e in self.copies(g)),(S,));self.assertFalse(self.secrets(g))

    def test_plagiarize_copies_only_ending_turn_not_previous_turns_or_owner_cards(self):
        g=self.game(owner_hand=(PLAGIARIZE,S));self.finish(g);self.play(g,S);g.apply(EndTurn(1));self.play(g,M,player=2);self.finish(g)
        self.assertEqual(tuple(e.card_id for e in self.copies(g)),(M,))

    def test_plagiarize_overflow_preserves_full_order_and_ordinary_burns(self):
        g=self.game(owner_hand=(PLAGIARIZE,)+(M,)*8);self.play(g,S,player=2);self.play(g,M,player=2);self.play(g,WPN,player=2);self.finish(g)
        copies=self.copies(g,None);self.assertEqual(tuple(e.card_id for e in copies),(S,M,WPN))
        self.assertEqual(tuple(e.zone for e in copies),(Zone.HAND,Zone.HAND,Zone.GRAVEYARD));self.portable(g)

    def test_plagiarize_full_hand_local_policy_keeps_secret(self):
        g=self.game(owner_hand=(PLAGIARIZE,FILL));g.apply(EndTurn(2));self.play(g,FILL);g.apply(EndTurn(1));self.play(g,S,player=2);self.finish(g)
        self.assertEqual(self.secrets(g),(PLAGIARIZE,));self.assertFalse(self.copies(g,None))

    def test_plagiarize_reveal_and_each_copy_wait_restore_exact_original_queue(self):
        for mode in('reveal_wait','copy_wait'):
            g=self.game(mode=mode,watch=True);self.play(g,S,player=2);self.play(g,M,player=2);self.finish(g)
            count=0
            while g.state.pending_choice:
                g=self.portable(g);self.choose(g);count+=1
            self.assertEqual(count,1 if mode=='reveal_wait'else 2)
            self.assertEqual(tuple(e.card_id for e in self.copies(g)),(S,M));self.portable(g)

    def test_plagiarize_failed_end_action_and_copy_wait_choice_roll_back_fully(self):
        g=self.game(mode='end_fail',watch=True);self.play(g,S,player=2);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.finish(g)
        self.assertEqual(g.snapshot(),before)
        g=self.game(mode='copy_wait',watch=True);self.play(g,S,player=2);self.finish(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(len(self.copies(g)),1)

    def test_historical_nonminion_copy_codec_rejects_future_or_changed_committed_faces(self):
        g=self.game();self.play(g,S,player=2);face=g.state.play_history[-1].played_face
        effect=CopyCard(face,1,mode='base',source_id=g.state.players[1].secrets[0])
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state);unbound=FrameCodec(g.mechanics,g.registry)
        self.assertEqual(codec.decode(codec.encode(effect)),effect)
        for bad in(replace(face,play_id=face.play_id+1),replace(face,source_id=g.state.players[2].hero_id)):
            with self.assertRaises(ValueError):codec.decode(unbound.encode(replace(effect,card=bad)))
        for delta in(dict(mode='current'),dict(destination=Zone.DECK),dict(cost=CostSpec(delta=-1)),dict(source_id=None)):
            with self.assertRaises(ValueError):replace(effect,**delta)

    def test_forged_historical_copy_rejects_at_actual_execution_and_rolls_back(self):
        g=self.game(mode='copy_forged',enemy_hand=(S,OP));self.play(g,S,player=2);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,OP,player=2)
        self.assertEqual(g.snapshot(),before)

    def test_opponent_view_hides_original_secret_menu_copy_queue_and_copied_hand(self):
        g=self.game(PERJURY);self.assertNotIn(PERJURY,json.dumps(g.for_player(2).observe()));self.finish(g)
        view=json.dumps(g.for_player(2).observe());self.assertNotIn('resolution_frame',view);self.assertNotIn(A,view)
        self.pick(g,A);self.assertNotIn(A,json.dumps(g.for_player(2).observe()))
        g=self.game(mode='copy_wait',watch=True);self.play(g,S,player=2);self.finish(g)
        view=json.dumps(g.for_player(2).observe());self.assertNotIn('copy_origin',view);self.assertNotIn('played_face',view);self.portable(g)

    def test_real_local_host_perjury_executes_complete_other_class_offer_and_cast(self):
        f=host();g=Game.from_scenario(Scenario((PlayerSetup('HERO_03',hand=(PERJURY,),mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=('CORE_EX1_162',)*8,mana=10,max_mana=10)),seed=644,generation_context=f.context),f.registry)
        self.play(g,PERJURY);g.apply(EndTurn(1));self.finish(g)
        complete=resolve_candidates(f.registry,f.context,'constructed.cards',native.SECRETS,current_class=CardClass.ROGUE)
        self.assertTrue({o.card_id for o in g.state.pending_choice.options}<={m.card_id for m in complete})
        chosen=g.state.pending_choice.options[0].card_id;self.pick(g,chosen)
        self.assertIn(chosen,self.secrets(g));self.assertEqual(g.state.cast_history[-1].origin,'effect')

    def test_real_local_host_plagiarize_copies_actual_standard_minion(self):
        f=host();g=Game.from_scenario(Scenario((PlayerSetup('HERO_03',hand=(PLAGIARIZE,),mana=10,max_mana=10),
            PlayerSetup('HERO_08',hand=('CORE_EX1_162',),deck=('CORE_EX1_162',)*8,mana=10,max_mana=10)),seed=644,generation_context=f.context),f.registry)
        self.play(g,PLAGIARIZE);g.apply(EndTurn(1));ident=self.play(g,'CORE_EX1_162',player=2);self.finish(g)
        self.assertEqual([(e.card_id,e.origin_entity_id)for e in self.copies(g)],[('CORE_EX1_162',ident)])


if __name__=='__main__':unittest.main()
