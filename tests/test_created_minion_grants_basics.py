"""Real gift recipes installed before acquisition; complete paired discovery is open."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import unittest

from hs_sim.engine import CreatedMinionGrant
from hs_sim.engine.actions import Attack, EndTurn, PlayCard, SelectChoice
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Destroy, Draw,
    GainArmor, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.game import Game, PlayerSetup, Scenario
from hs_sim.engine.model import (CardDefinition, CardPreview, CardType, CostSpec,
    Keyword, TriggerSpec, Zone)
from hs_sim.engine.registry import Registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

ROOT=Path(__file__).resolve().parents[1]
NATIVE='CS2_120';YETI='CS2_182';POLICY='full_health_enchantments'
PIN='468a09bec80cb283ab4190df9753313b786d83e57f15932dd0bcbcaa51c3c57a'
RECIPES={
    'EDR_100t':CreatedMinionGrant(attack=3,keywords=(Keyword.LIFESTEAL,)),
    'EDR_100t3':CreatedMinionGrant(health=4,keywords=(Keyword.TAUNT,)),
    'EDR_100t9':CreatedMinionGrant(keywords=(Keyword.REBORN,),reborn_policy=POLICY),
    'EDR_100t2':CreatedMinionGrant(attack=-2),
}


def evidence():
    packet=json.loads((ROOT/'data/support/creation-minion-grants-basics.json').read_bytes())
    if canonical_digest(packet)!=PIN:raise ValueError('Complete creation grant evidence changed')
    return packet


def make(gift,player,source):
    evidence()
    if gift not in RECIPES:raise ValueError('Unsupported isolated gift recipe')
    return AddToHand(player,YETI if gift=='EDR_100t2' else NATIVE,source,
        cost=CostSpec(delta=-2) if gift=='EDR_100t2' else None,minion_grant=RECIPES[gift])


def registry():
    r=Registry('created-minion-grants-independent-v1');raw={x['id']:x for x in evidence()['records']}
    r.register_card(CardDefinition('cg.hero','Diagnostic hero',CardType.HERO,health=30))
    for cid in (NATIVE,YETI):
        x=raw[cid];r.register_card(CardDefinition(cid,x['name'],CardType.MINION,cost=x['cost'],
            attack=x['attack'],health=x['health'],metadata=metadata_from_record(x)))
    r.register_card(CardDefinition('cg.filler','Diagnostic filler',CardType.MINION,health=1))
    r.register_card(CardDefinition('cg.weapon','Invalid grant carrier',CardType.WEAPON,attack=1,durability=2))
    r.register_behavior('cg.cb.noop',lambda c:())
    r.register_card(CardDefinition('cg.hidden','Private spell',CardType.SPELL,on_play='cg.cb.noop'))
    for tag,event in (('probe','card_created'),('added','card_added_to_hand'),('burned','card_burned')):
        def inspect(c):
            e=c.state.entities[c.event.target_id]
            if e.card_id not in (NATIVE,YETI):return ()
            amount=e.cost+e.attack+e.max_health+10*(Keyword.TAUNT in e.keywords)+20*(Keyword.LIFESTEAL in e.keywords)
            return (GainArmor(c.player_id,amount),)
        r.register_behavior('cg.cb.'+tag,inspect)
        r.register_card(CardDefinition('cg.'+tag,tag+' observer',CardType.MINION,health=3,
            triggers=(TriggerSpec(event,'cg.cb.'+tag),)))
    r.register_behavior('cg.cb.wait_after',lambda c:(RequestChoice(c.player_id,(
        ChoiceOption('done','Continue',()),ChoiceOption('skip','Also continue',()),),c.source_id),)
        if c.state.entities[c.event.target_id].card_id==NATIVE else ())
    r.register_card(CardDefinition('cg.wait_after','Post-creation waiting diagnostic',CardType.MINION,health=3,
        triggers=(TriggerSpec('card_created','cg.cb.wait_after'),)))
    def fail(c):raise ResolutionError('Deliberate atomic minion grant rollback')
    r.register_behavior('cg.cb.fail',fail)
    r.register_card(CardDefinition('cg.fail','Rollback observer',CardType.MINION,health=3,
        triggers=(TriggerSpec('card_created','cg.cb.fail'),)))
    def reference(c):
        return CardReference.capture(next(c.state.entities[i] for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id==NATIVE))
    def before(c):
        return (RequestChoice(c.player_id,(
            ChoiceOption('gift','Isolated Plate Up recipe',(make('EDR_100t3',c.player_id,c.source_id),),
                card_id=NATIVE,preview=CardPreview(2,2,7,7,0,(Keyword.TAUNT,))),
            ChoiceOption('skip','No card',()),),c.source_id),)
    bodies={
        'taunt':lambda c:(make('EDR_100t3',c.player_id,c.source_id),),
        'lifesteal':lambda c:(make('EDR_100t',c.player_id,c.source_id),),
        'reborn':lambda c:(make('EDR_100t9',c.player_id,c.source_id),),
        'discount':lambda c:(make('EDR_100t2',c.player_id,c.source_id),),
        'ordinary':lambda c:(AddToHand(c.player_id,NATIVE,c.source_id),),
        'burn':lambda c:(Draw(c.player_id),make('EDR_100t3',c.player_id,c.source_id)),
        'before':before,
        'copy':lambda c:(CopyCard(reference(c),c.player_id,source_id=c.source_id),),
        'basecopy':lambda c:(CopyCard(reference(c),c.player_id,mode='base',source_id=c.source_id),),
        'deck':lambda c:(MoveCard(reference(c),c.player_id,Zone.DECK,position='top'),),
        'draw':lambda c:(Draw(c.player_id),),
        'kill':lambda c:(Destroy(c.target_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'hurt':lambda c:(Damage(c.state.players[c.player_id].hero_id,3),),
        'spell_carrier':lambda c:(AddToHand(c.player_id,'cg.hidden',c.source_id,minion_grant=RECIPES['EDR_100t3']),),
        'weapon_carrier':lambda c:(AddToHand(c.player_id,'cg.weapon',c.source_id,minion_grant=RECIPES['EDR_100t3']),),
        'source_missing':lambda c:(AddToHand(c.player_id,NATIVE,99999,minion_grant=RECIPES['EDR_100t3']),),
        'bad_branch':lambda c:(RequestChoice(c.player_id,(
            ChoiceOption('valid','Valid',(make('EDR_100t3',c.player_id,c.source_id),)),
            ChoiceOption('wrong','Unsupported carrier',(AddToHand(c.player_id,'cg.hidden',c.source_id,
                minion_grant=RECIPES['EDR_100t3']),)),),c.source_id),),
    }
    for name,body in bodies.items():
        r.register_behavior('cg.cb.make.'+name,body)
        r.register_card(CardDefinition('cg.make.'+name,name+' diagnostic',CardType.SPELL,cost=1,
            on_play='cg.cb.make.'+name,requires_target=name in ('kill','silence','bounce')))
    return r


class CreatedMinionGrantTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('cg.hero',hand=hand,board=board,deck=('cg.filler',)*12,mana=10,max_mana=10),
            PlayerSetup('cg.hero',hand=enemy_hand,deck=('cg.filler',)*12,mana=10,max_mana=10),
        ),seed=114),registry())
    def play(self,g,card,target=None):
        p=g.state.active_player
        i=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==card)
        return g.apply(PlayCard(p,i,target))
    def created(self,g):
        return g.state.entities[next(e.target_id for e in reversed(g.events) if e.kind=='card_created')]
    def armor(self,g):return g.state.entities[g.state.players[1].hero_id].armor
    def choose(self,g,key='gift'):
        q=g.state.pending_choice;return g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()))
        variants=(Game.from_snapshot(saved,registry()),g.clone(),replay(build_replay(g),registry()))
        for other in variants:self.assertEqual(other.snapshot(),saved)
        return variants
    def nodes(self,value,suffix):
        if isinstance(value,dict):
            if value.get('type','').endswith('.'+suffix):yield value['fields']
            for item in value.values():yield from self.nodes(item,suffix)
        elif isinstance(value,list):
            for item in value:yield from self.nodes(item,suffix)
    def reject(self,saved):
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as caught:Game.from_snapshot(saved,registry())
        self.assertNotIn('digest mismatch',str(caught.exception))

    def test_complete_raw_pin_and_real_recipe_scope(self):
        p=evidence();rows={x['id']:x for x in p['records']}
        self.assertEqual(len(rows),11);self.assertEqual(set(p['isolated_recipes']),set(RECIPES))
        self.assertEqual(rows['EDR_100t3e']['text'],rows['EDR_100t3']['text'])
        self.assertIn('传说',rows['EDR_102']['text']);self.assertNotIn('EDR_102',registry().cards)
        self.assertFalse(p['whole_dark_gift_implemented']);self.assertFalse(p['formal_gift_pool'])
        for recipe in RECIPES:self.assertNotIn(recipe,registry().cards)
        with self.assertRaisesRegex(ValueError,'Unsupported isolated'):make('EDR_100t4',1,None)

    def test_first_created_and_added_observers_see_complete_health_and_taunt(self):
        g=self.game(('cg.make.taunt',),('cg.probe','cg.added'));self.play(g,'cg.make.taunt')
        e=self.created(g);self.assertEqual((e.attack,e.health,e.max_health),(2,7,7))
        self.assertIn(Keyword.TAUNT,e.keywords);self.assertEqual(self.armor(g),42)
        self.assertEqual([x.kind for x in g.events if x.kind in ('stored_keyword_granted','stored_card_buffed','ability_granted')],[])
        self.portable(g)

    def test_old_same_name_hand_card_keeps_original_values_and_grant_source_is_creator(self):
        g=self.game(('cg.make.lifesteal',NATIVE));old=g.state.players[1].hand[1];source=g.state.players[1].hand[0]
        self.play(g,'cg.make.lifesteal');e=self.created(g)
        self.assertEqual((g.state.entities[old].attack,g.state.entities[old].max_health),(2,3))
        self.assertEqual((e.attack,e.max_health),(5,3));self.assertIn(Keyword.LIFESTEAL,e.keywords)
        self.assertEqual(e.enchantments[0].source_id,source);self.assertEqual(e.abilities[0].source_id,source)
        self.assertNotEqual(e.id,old);self.portable(g)

    def test_real_discount_attack_recipe_installs_original_cost_and_stats_before_observers(self):
        g=self.game(('cg.make.discount',),('cg.probe','cg.added'));self.play(g,'cg.make.discount')
        e=self.created(g);self.assertEqual((e.card_id,e.cost,e.attack,e.max_health),(YETI,2,2,5))
        self.assertEqual(self.armor(g),18);self.assertEqual(len(e.enchantments),2)
        self.portable(g)

    def test_full_hand_burn_has_complete_grants_without_a_hand_acquisition_or_death(self):
        g=self.game(('cg.make.burn',)+('cg.filler',)*9,('cg.probe','cg.burned'))
        self.play(g,'cg.make.burn');e=self.created(g)
        self.assertEqual((e.zone,e.health),(Zone.GRAVEYARD,7));self.assertIn(Keyword.TAUNT,e.keywords)
        self.assertEqual(self.armor(g),42);self.assertEqual(len(g.state.players[1].hand),10)
        self.assertFalse(any(x.entity_id==e.id for x in g.state.hand_entries))
        self.assertEqual(g.state.death_history,[]);self.portable(g)

    def test_ordinary_creation_does_not_get_an_implicit_grant(self):
        g=self.game(('cg.make.ordinary',));self.play(g,'cg.make.ordinary');e=self.created(g)
        self.assertEqual((e.attack,e.max_health),(2,3));self.assertEqual(e.enchantments,[])
        self.assertEqual(e.abilities,[]);self.portable(g)

    def test_direct_creation_has_no_random_selection_and_only_original_payment(self):
        g=self.game(('cg.make.taunt',));before=g.snapshot();self.play(g,'cg.make.taunt')
        self.assertEqual(g.snapshot()['rng_state'],before['rng_state'])
        self.assertEqual(g.state.players[1].mana,9)
        self.assertEqual(len([x for x in g.events if x.kind=='card_created']),1)

    def test_real_lifesteal_recipe_is_active_after_play(self):
        g=self.game(('cg.make.lifesteal','cg.make.hurt'));self.play(g,'cg.make.hurt');self.play(g,'cg.make.lifesteal')
        created=self.created(g).id;self.play(g,NATIVE)
        g.apply(EndTurn(1));g.apply(EndTurn(2));g.apply(Attack(1,created,g.state.players[2].hero_id))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,25);self.portable(g)

    def test_creation_reborn_recipe_follows_existing_full_health_return_and_consumption(self):
        g=self.game(('cg.make.reborn','cg.make.kill','cg.make.kill'));source=g.state.players[1].hand[0]
        self.play(g,'cg.make.reborn');e=self.created(g);self.assertEqual(e.abilities[0].reborn_policy,POLICY)
        self.play(g,NATIVE);self.play(g,'cg.make.kill',e.id);new=g.state.entities[g.state.players[1].board[0]]
        self.assertEqual(new.health,3);self.assertNotIn(Keyword.REBORN,new.keywords)
        self.assertEqual(new.abilities[0].source_id,source)
        self.play(g,'cg.make.kill',new.id);self.assertEqual(g.state.players[1].board,[]);self.portable(g)

    def test_current_and_base_copies_reuse_existing_attachment_policy(self):
        for mode in ('copy','basecopy'):
            with self.subTest(mode=mode):
                g=self.game(('cg.make.taunt','cg.make.'+mode));self.play(g,'cg.make.taunt');old=self.created(g)
                self.play(g,'cg.make.'+mode);new=self.created(g)
                self.assertEqual((new.max_health,Keyword.TAUNT in new.keywords),(7,True) if mode=='copy' else (3,False))
                self.assertNotEqual(new.id,old.id)
                if mode=='copy':self.assertNotEqual(new.enchantments[0].id,old.enchantments[0].id)
                self.portable(g)

    def test_hand_to_deck_and_draw_retains_original_attachments(self):
        g=self.game(('cg.make.taunt','cg.make.deck','cg.make.draw'));self.play(g,'cg.make.taunt');e=self.created(g)
        self.play(g,'cg.make.deck');self.play(g,'cg.make.draw')
        current=g.state.entities[e.id];self.assertEqual((current.zone,current.max_health),(Zone.HAND,7))
        self.assertEqual(current.enchantments,e.enchantments);self.assertIn(Keyword.TAUNT,current.keywords);self.portable(g)

    def test_silence_and_return_to_hand_use_existing_reset_semantics(self):
        for action in ('silence','bounce'):
            with self.subTest(action=action):
                g=self.game(('cg.make.taunt','cg.make.'+action));self.play(g,'cg.make.taunt');e=self.created(g)
                self.play(g,NATIVE);self.play(g,'cg.make.'+action,e.id)
                current=g.state.entities[e.id];self.assertEqual(current.max_health,3)
                self.assertNotIn(Keyword.TAUNT,current.keywords);self.assertEqual(current.enchantments,[]);self.portable(g)

    def test_wait_before_creation_freezes_typed_payload_and_visible_preview(self):
        g=self.game(('cg.make.before',));self.play(g,'cg.make.before');q=g.state.pending_choice
        self.assertEqual(q.options[0].preview.health,7);self.assertEqual(g.state.players[1].hand,[])
        self.assertEqual(len(list(self.nodes(g.snapshot()['resolution_frame'],'CreatedMinionGrant'))),1)
        for other in (g,*self.portable(g)):
            self.choose(other);self.assertEqual(self.created(other).health,7)
            self.assertEqual(other.state.players[1].mana,9);self.portable(other)

    def test_wait_after_creation_already_has_full_material_and_resumes_without_duplication(self):
        g=self.game(('cg.make.taunt',),('cg.wait_after',));self.play(g,'cg.make.taunt')
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.created(g).health,7)
        for other in (g,*self.portable(g)):
            self.choose(other,'done');self.assertEqual(len([x for x in other.events if x.kind=='card_created']),1)
            self.assertEqual(self.created(other).health,7);self.portable(other)

    def test_invalid_carriers_and_missing_source_roll_back_before_allocation(self):
        for action in ('spell_carrier','weapon_carrier','source_missing'):
            with self.subTest(action=action):
                g=self.game(('cg.make.'+action,));before=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,'cg.make.'+action)
                self.assertEqual(g.snapshot(),before)

    def test_invalid_unselected_choice_branch_is_rejected_at_waiting_boundary(self):
        g=self.game(('cg.make.bad_branch',));before=g.snapshot()
        with self.assertRaises(ValueError):self.play(g,'cg.make.bad_branch')
        self.assertEqual(g.snapshot(),before)

    def test_observer_failure_rolls_back_creation_and_all_attachment_ids(self):
        g=self.game(('cg.make.taunt',),('cg.fail',));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Deliberate'):self.play(g,'cg.make.taunt')
        self.assertEqual(g.snapshot(),before)

    def test_payload_is_immutable_and_rejects_empty_wrong_types_or_unrelated_ability_programs(self):
        grant=RECIPES['EDR_100t3']
        with self.assertRaises(FrozenInstanceError):grant.health=1
        for kw in ({},{'attack':True},{'health':1.5},{'keywords':[Keyword.TAUNT]},
            {'keywords':(Keyword.TAUNT,Keyword.TAUNT)},{'keywords':(Keyword.FRENZY,)},
            {'keywords':(Keyword.TAUNT,),'reborn_policy':POLICY}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):CreatedMinionGrant(**kw)
        with self.assertRaises(TypeError):CreatedMinionGrant(battlecry='unknown')
        with self.assertRaises(ValueError):AddToHand(1,NATIVE,minion_grant={'health':4})

    def test_rehashed_waiting_payload_corruption_cannot_bypass_strict_validation(self):
        g=self.game(('cg.make.before',));self.play(g,'cg.make.before')
        for field,value in (('health',True),('reborn_policy',POLICY),('unexpected',1)):
            bad=deepcopy(g.snapshot());row=next(self.nodes(bad['resolution_frame'],'CreatedMinionGrant'));row[field]=value
            self.reject(bad)
        bad=deepcopy(g.snapshot());row=next(self.nodes(bad['resolution_frame'],'CreatedMinionGrant'));del row['keywords'];self.reject(bad)

    def test_payload_registration_and_previous_schema_rejection(self):
        g=self.game();saved=g.snapshot()
        self.assertEqual((g.ruleset.id,g.mechanics.version,saved['schema_version']),('prototype-v302',CORE_EFFECTS_VERSION,265))
        self.assertIn('hs_sim.engine.card_creation.CreatedMinionGrant',g.mechanics.signature['payload_types'])
        saved['schema_version']=226
        with self.assertRaisesRegex(SnapshotError,'1 through 264'):Game.from_snapshot(saved,registry())

    def test_player_command_and_private_views_keep_internal_grant_and_enemy_hand_hidden(self):
        g=self.game(('cg.make.taunt',),enemy_hand=('cg.hidden',));port=g.for_player(1);public=port.legal_actions()
        action=next(a for a in public['actions'] if a['type']=='play_card')
        result=port.submit({'revision':public['revision'],'action':action});self.assertTrue(result['accepted'],result['error'])
        own=port.legal_actions()['observation']['players'][0]['hand'][0]
        self.assertEqual((own['attack'],own['max_health']),(2,7))
        for seat in (1,2):
            wire=json.dumps((g.for_player(seat).observe(),g.for_player(seat).legal_actions()),ensure_ascii=False)
            for field in ('CreatedMinionGrant','minion_grant','resolution_frame','source_sha256'):self.assertNotIn(field,wire)
            if seat==1:self.assertNotIn('cg.hidden',wire)
        self.portable(g)


if __name__=='__main__':unittest.main()
