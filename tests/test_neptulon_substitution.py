"""Actual Neptulon entry and original forced-combat substitution boundaries."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards.neptulon_substitution import CARD,HANDS,PROFILE,BODY,load_batch,register_neptulon_substitution
from hs_sim.cards.simple_followup_p74_cards import register_simple_followup_p74_cards
from hs_sim.engine import (Attack,CardDefinition,CardType,Game,Keyword,PlayerSetup,ResolutionError,
    Scenario,SnapshotError,TriggerSpec,Zone,character_attacks)
from hs_sim.engine.attack_substitution import (AttackSubstitutionProfile,ContinueAttackSubstitutes,
    SubstituteAttackLink,CheckAttackSubstitutes,reject_choice_control)
from hs_sim.engine.effects import (ChoiceOption,Damage,Destroy,ForceAttack,Freeze,InvokeBehavior,
    RequestChoice,ReturnToHand,Silence,Summon,Transform)
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.model import BoardPresenceReference,CardClass,CardMetadata,Rarity
from hs_sim.engine.pools import GenerationContext,PoolDefinition,PoolMember
from hs_sim.engine.registry import Registry
from hs_sim.engine.serialization import canonical_hash,SNAPSHOT_SCHEMA_VERSION
from tools import card_batch as batch

S='k567.'
HERO,POWER,UNIT,BIG,LETHAL,DORMANT,WATCH,FREEZE,QUIET,KILL,BOUNCE,FORCE,SUMMON,FAULT=(S+x for x in
    ('hero','power','unit','big','lethal','dormant','watch','freeze','quiet','kill','bounce','force','summon','fault'))
CTX=GenerationContext('k567-neptulon-native','experimental')


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    if mode=='frontier':
        from hs_sim.local_pool_format import build_cn37_local_pool_format
        r=build_cn37_local_pool_format().registry
    else:
        r=Registry('k567-small-native');register_simple_followup_p74_cards(r);register_neptulon_substitution(r)
    def fail(c):raise ResolutionError('k567 deliberate resume failure')
    def watch(c):
        e=c.event;source=c.state.entities.get(e.source_id)
        if source is None:return ()
        is_parent=source.card_id==CARD and e.kind=='attack_declared'
        is_child=source.card_id in HANDS and e.kind=='attack_declared'
        first_child=source.card_id in HANDS and e.kind=='attack_finished' and len([
            x for x in c.state.character_attack_history if x.source_card_id in HANDS and x.terminal is not None])==1
        if (mode=='wait_parent' and is_parent) or (mode=='wait_child' and is_child and len([
                x for x in c.state.character_attack_history if x.source_card_id in HANDS])==1):
            return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',
                (InvokeBehavior(FAULT,c.source_id,c.player_id),))),c.source_id),)
        if mode=='silence_parent_before' and is_parent:return(Silence(source.id),)
        if not first_child:return ()
        parent=next((x for x in c.state.entities.values()if x.card_id==CARD and x.zone==Zone.BOARD),None)
        later=next((c.state.entities[i]for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id in HANDS and i!=source.id),None)
        if mode=='kill_parent' and parent is not None:return(Destroy(parent.id,c.source_id),)
        if mode=='silence_parent' and parent is not None:return(Silence(parent.id),)
        if mode=='bounce_hand' and later is not None:return(ReturnToHand(later.id),)
        if mode=='transform_hand' and later is not None:return(Transform(later.id,UNIT),)
        if mode=='new_hand':return(Summon(c.player_id,HANDS[0]),)
        if mode=='terminal':return(Damage(c.state.players[3-c.player_id].hero_id,100,c.source_id),)
        return ()
    r.register_behavior(FAULT,fail);r.register_behavior(WATCH,watch);r.register_behavior(POWER,lambda c:())
    r.register_card(CardDefinition(POWER,POWER,CardType.HERO_POWER,cost=2,on_use=POWER,
        metadata=CardMetadata(False,(CardClass.MAGE,),None)))
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=60,initial_hero_power=POWER,
        metadata=CardMetadata(False,(CardClass.MAGE,),None)))
    for cid,attack,health,dormant in ((UNIT,1,3,0),(BIG,5,40,0),(LETHAL,20,40,0),(DORMANT,4,2,None)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=attack,health=health,dormant_turns=dormant))
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,attack=0,health=50,
        triggers=(TriggerSpec('attack_declared',WATCH),TriggerSpec('attack_finished',WATCH))))
    bodies={FREEZE:lambda c:(Freeze(c.target_id),),QUIET:lambda c:(Silence(c.target_id),),
        KILL:lambda c:(Destroy(c.target_id,c.source_id),),BOUNCE:lambda c:(ReturnToHand(c.target_id),),
        FORCE:lambda c:(ForceAttack(next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==CARD),c.target_id),),
        SUMMON:lambda c:(Summon(c.player_id,CARD),),S+'sleep':lambda c:(MakeDormant(c.target_id,2,c.source_id),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,requires_target=cid!=SUMMON))
    if mode=='frontier':r.register_pool(PoolDefinition('constructed.past.cards','neptulon-only-native-diagnostic-v1',CTX.target_id,CTX.mode,
        (PoolMember(CARD),),complete=True))
    r.validate();return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
    return saved


class NeptulonSubstitutionTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(fixture)

    def game(self,*,hand=(),board=(CARD,*HANDS),enemy=(BIG,),mode='normal',player=1):
        self.mode=mode
        own=PlayerSetup(HERO,hand=hand,board=board,deck=(UNIT,)*6,mana=20,max_mana=20,mana_cap=20)
        other=PlayerSetup(HERO,board=enemy,deck=(UNIT,)*6,mana=10,max_mana=10)
        return Game.from_scenario(Scenario((own,other)if player==1 else(other,own),active_player=player,
            seed=567,generation_context=CTX),fixture(mode))

    def hit(self,g,target=None,player=1):
        return g.apply(Attack(player,self.entity(g,CARD,player,'board').id,
            self.entity(g,BIG,3-player,'board').id if target is None else target))

    def parent(self,g):return next(r for r in g.state.character_attack_history if r.source_card_id==CARD)

    def test_complete_parent_hands_primary_faces_and_old_native_definitions(self):
        data=load_batch();raw={r['id']:r for r in batch.read(data['source'])};r=fixture()
        for x in data['cards']+data['existing_dependencies']:
            self.assertEqual(x['record'],raw[x['record']['id']])
        for face in data['official_faces']:batch.check_face(raw[CARD],face['face'],face['locale'],{})
        self.assertEqual((r.card(CARD).cost,r.card(CARD).attack,r.card(CARD).health),(10,7,7))
        self.assertEqual(tuple(a.card_id for a in r.card(CARD).colossal),HANDS)
        for cid in HANDS:self.assertEqual((r.card(cid).cost,r.card(cid).attack,r.card(cid).health,r.card(cid).keywords),(4,4,2,(Keyword.IMMUNE_WHILE_ATTACKING,)))
        self.assertFalse(data['cn_calibrated']);self.assertFalse(data['formal_pool_complete'])

    def test_real_paid_entry_colossal_rush_two_hands_replace_damage_and_parent_retaliation(self):
        g=self.game(hand=(CARD,),board=());source=self.play(g,CARD)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[HANDS[0],CARD,HANDS[1]])
        self.assertEqual(g.state.players[1].mana,10)
        self.assertFalse(any(type(a)is Attack and a.attacker_id==source and a.defender_id==g.state.players[2].hero_id for a in g.legal_actions()))
        self.hit(g);self.assertEqual(self.entity(g,BIG,2,'board').damage,8)
        self.assertEqual((g.state.entities[source].damage,g.state.entities[source].attacks_this_turn),(0,1))
        self.assertTrue(all(self.entity(g,cid,zone='board').damage==0 for cid in HANDS))
        self.assertEqual(self.parent(g).terminal.status,'replaced');self.assertIsNone(self.parent(g).combat)
        self.assertEqual(len(character_attacks(g.state,1,forced=True)),2);self.portable(g)

    def test_windfury_two_parent_opportunities_four_forced_hands_and_no_hand_payment(self):
        g=self.game();self.hit(g);self.hit(g)
        self.assertEqual(self.entity(g,BIG,2,'board').damage,16)
        self.assertEqual(self.entity(g,CARD,zone='board').attacks_this_turn,2)
        self.assertEqual([self.entity(g,cid,zone='board').attacks_this_turn for cid in HANDS],[0,0])
        self.assertFalse(any(type(a)is Attack and a.attacker_id==self.entity(g,CARD,zone='board').id for a in g.legal_actions()))

    def test_no_hands_uses_normal_seven_damage_and_reciprocal_combat(self):
        g=self.game(board=(CARD,));self.hit(g)
        self.assertEqual((self.entity(g,BIG,2,'board').damage,self.entity(g,CARD,zone='board').damage),(7,5))
        self.assertIsNone(self.parent(g).substitution);self.assertEqual(self.parent(g).terminal.status,'completed')

    def test_all_own_hands_beyond_original_pair_without_enemy_or_dormant_members(self):
        g=self.game(hand=(S+'sleep',),board=(CARD,*HANDS,*HANDS),enemy=(BIG,HANDS[1]))
        last=g.state.players[1].board[-1];self.play(g,S+'sleep',last);self.hit(g)
        p=self.parent(g).substitution;self.assertEqual(len(p.members),3);self.assertEqual(self.entity(g,BIG,2,'board').damage,12)
        self.assertTrue(all(g.state.entities[m.entity_id].controller==1 for m in p.members))
        self.assertNotIn(last,[m.entity_id for m in p.members])

    def test_frozen_and_exhausted_hand_still_forced_and_manual_attack_is_independent(self):
        g=self.game(hand=(FREEZE,));hand=self.entity(g,HANDS[0],zone='board').id;target=self.entity(g,BIG,2,'board').id
        g.apply(Attack(1,hand,target));self.play(g,FREEZE,hand);self.hit(g)
        self.assertEqual(g.state.entities[hand].attacks_this_turn,1);self.assertEqual(self.entity(g,BIG,2,'board').damage,12)
        self.assertEqual(len(character_attacks(g.state,1,forced=True)),2)

    def test_silenced_parent_loses_replacement_and_hand_loses_immunity_but_not_identity(self):
        g=self.game(hand=(QUIET,));self.play(g,QUIET,self.entity(g,CARD,zone='board').id);self.hit(g)
        self.assertIsNone(self.parent(g).substitution);self.assertEqual(self.entity(g,BIG,2,'board').damage,7)
        g=self.game(hand=(QUIET,));first=self.entity(g,HANDS[0],zone='board').id;self.play(g,QUIET,first);self.hit(g)
        self.assertEqual(g.state.entities[first].zone,Zone.GRAVEYARD);self.assertEqual(len(self.parent(g).substitution.attempts),2)
        self.assertEqual(self.entity(g,BIG,2,'board').damage,8)

    def test_source_silenced_by_earlier_declaration_listener_falls_back_to_normal(self):
        g=self.game(board=(WATCH,CARD,*HANDS),mode='silence_parent_before');self.hit(g)
        self.assertIsNone(self.parent(g).substitution);self.assertEqual(self.entity(g,BIG,2,'board').damage,7)

    def test_original_target_dies_first_hand_later_hand_skips_without_retarget(self):
        g=self.game(enemy=(UNIT,BIG));target=self.entity(g,UNIT,2,'board').id;self.hit(g,target)
        p=self.parent(g).substitution;self.assertEqual([a.child_window_id is None for a in p.attempts],[False,True])
        self.assertEqual(self.entity(g,BIG,2,'board').damage,0);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual(self.entity(g,CARD,zone='board').damage,0)

    def test_later_original_hand_bounce_or_transform_skips_and_new_hand_does_not_join(self):
        for mode in ('bounce_hand','transform_hand','new_hand'):
            with self.subTest(mode=mode):
                g=self.game(board=(WATCH,CARD,*HANDS),mode=mode);self.hit(g)
                p=self.parent(g).substitution
                self.assertEqual(len(p.members),2)
                self.assertEqual(self.entity(g,BIG,2,'board').damage,8 if mode=='new_hand' else 4)
                self.assertEqual([a.child_window_id is None for a in p.attempts],[False,mode!='new_hand'])

    def test_accepted_source_death_or_silence_does_not_revoke_remaining_hand(self):
        for mode in ('kill_parent','silence_parent'):
            with self.subTest(mode=mode):
                g=self.game(board=(WATCH,CARD,*HANDS),mode=mode);self.hit(g)
                self.assertEqual(self.entity(g,BIG,2,'board').damage,8)
                self.assertEqual(self.parent(g).terminal.status,'replaced');self.assertEqual(self.parent(g).substitution.status,'completed')
                self.assertEqual(len(character_attacks(g.state,1,forced=True)),2)

    def test_actual_forced_parent_uses_same_hook_without_parent_manual_payment(self):
        g=self.game(hand=(FORCE,));self.play(g,FORCE,self.entity(g,BIG,2,'board').id)
        self.assertTrue(self.parent(g).declaration.forced);self.assertEqual(self.entity(g,CARD,zone='board').attacks_this_turn,0)
        self.assertEqual(self.entity(g,BIG,2,'board').damage,8);self.portable(g)

    def test_parent_and_child_wait_restore_clone_replay_and_failed_resume_rollback(self):
        for mode in ('wait_parent','wait_child'):
            with self.subTest(mode=mode):
                g=self.game(board=(WATCH,CARD,*HANDS),mode=mode);self.hit(g)
                self.assertIsNotNone(g.state.pending_choice);restored=self.portable(g);before=g.snapshot()
                with self.assertRaises(ResolutionError):self.choose(g,'fault')
                self.assertEqual(g.snapshot(),before)
                for game in (g,restored):self.choose(game);self.assertEqual(self.entity(game,BIG,2,'board').damage,8)
                self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_terminal_after_first_child_keeps_actual_prefix_and_interrupts_parent(self):
        g=self.game(board=(WATCH,CARD,*HANDS),mode='terminal');self.hit(g)
        self.assertEqual(g.state.status,'finished');p=self.parent(g)
        self.assertEqual((p.terminal.status,p.substitution.status,len(p.substitution.attempts)),('interrupted','interrupted',1))
        self.assertEqual(g.state.action_windows,[]);self.portable(g)

    def test_second_seat_and_player_projection_keep_private_plans_private(self):
        g=self.game(player=2);self.hit(g,player=2)
        p=self.parent(g).substitution;self.assertEqual(p.window.player_id,2)
        for player in (1,2):
            view=json.dumps(g.for_player(player).observe())
            for secret in ('attack_substitution','character_attack_history','producer_link','declaration_sequence'):
                self.assertNotIn(secret,view)
        self.portable(g)

    def test_colossal_partial_capacity_and_generated_entry_keep_existing_appendage_pipeline(self):
        g=self.game(hand=(CARD,),board=(UNIT,)*5);self.play(g,CARD)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(sum(g.state.entities[i].card_id in HANDS for i in g.state.players[1].board),1)
        self.hit(g);self.assertEqual(self.entity(g,BIG,2,'board').damage,4)
        g=self.game(hand=(SUMMON,),board=());self.play(g,SUMMON)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[HANDS[0],CARD,HANDS[1]])
        self.assertFalse(g.state.battlecry_history);self.hit(g);self.assertEqual(self.entity(g,BIG,2,'board').damage,8)

    def test_real_frontier_discovery_restore_one_cost_entry_and_actual_substitution(self):
        g=self.game(hand=('GDB_857',),board=(),mode='frontier');self.play(g,'GDB_857');restored=self.portable(g)
        for game in (g,restored):
            self.choose(game,next(o.id for o in game.state.pending_choice.options if o.card_id==CARD))
            self.play(game,CARD);self.assertEqual(game.state.play_history[-1].cost,1);self.hit(game)
            self.assertEqual(self.entity(game,BIG,2,'board').damage,8)
        self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_rehashed_plan_member_prefix_child_and_source_tampering_rejected(self):
        g=self.game();self.hit(g);saved=g.snapshot()
        def bad(change):
            candidate=deepcopy(saved);change(candidate['state']['character_attack_history'][0]['substitution'])
            with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(candidate),fixture())
        # Snapshot uses the existing top-level state field; every forged copy has fresh hashes.
        bad(lambda p:p['members'].pop())
        bad(lambda p:p['attempts'].pop())
        bad(lambda p:p['attempts'][1].update(child_window_id=p['attempts'][0]['child_window_id']))
        bad(lambda p:p['source'].update(card_id=UNIT))

    def test_waiting_continuation_cannot_be_removed_duplicated_or_borrowed(self):
        g=self.game(board=(WATCH,CARD,*HANDS),mode='wait_child');self.hit(g);original=g.snapshot()
        def change(value,mode):
            if isinstance(value,dict):
                if value.get('type','').endswith('.ContinueAttackSubstitutes'):
                    value['fields']['index']+=1;return True
                return any(change(v,mode)for v in value.values())
            if isinstance(value,list):return any(change(v,mode)for v in value)
            return False
        for mode in ('index','removed','duplicate'):
            with self.subTest(mode=mode):
                saved=deepcopy(original)
                if mode=='index':self.assertTrue(change(saved,mode))
                else:
                    work=saved['resolution_frame']['fields']['continuation']['tuple']
                    index=next(i for i,x in enumerate(work)if x.get('type','').endswith('.ContinueAttackSubstitutes'))
                    if mode=='removed':work.pop(index)
                    else:work.insert(index,deepcopy(work[index]))
                with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),fixture('wait_child'))

    def test_strict_profile_control_shape_and_old_schema_rejection(self):
        with self.assertRaises(ValueError):AttackSubstitutionProfile(PROFILE,CARD,BODY,(HANDS[0],HANDS[0]))
        with self.assertRaises(ValueError):ForceAttack(1,2,producer_link=SubstituteAttackLink(1,0))
        with self.assertRaises(ValueError):ContinueAttackSubstitutes(True,0)
        with self.assertRaises(ValueError):reject_choice_control((ChoiceOption('bad','Bad',(ContinueAttackSubstitutes(1,0),)),))
        saved=self.game().snapshot();saved['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,fixture())


if __name__=='__main__':unittest.main()
