"""Three actual ordinary gift recipes reuse the existing discovery and combat kernel."""
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType, CreatedMinionGrant,
    DiscoverFromPool, DiscoveryGiftPool, DiscoveryMinionGift, EndTurn, Game, GenerationContext,
    IllegalAction, Keyword, PlayCard, PlayerSetup, PoolCard, PoolDefinition, PoolMember, PoolQuery,
    Registry, Scenario, SelectChoice)
from hs_sim.engine.effects import Damage
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import canonical_digest

ROOT=Path(__file__).resolve().parents[1]
PIN='eb52c8858e07e8c170eab71bd5980b8b94c15212d7a964af9dd0f16b00b8bff1'
SOURCE='EDR_105';MINIONS=('CS2_118','CS2_125','CS2_127')
NEW=('EDR_100t1','EDR_100t6','EDR_100t13')
CONTEXT=GenerationContext('dark-gift-keyword-foundation','experimental')


def evidence():
    value=json.loads((ROOT/'data/support/dark-gift-keyword-recipes.json').read_bytes())
    if canonical_digest(value)!=PIN:raise ValueError('Full gift keyword evidence changed')
    return value


def recipes(ids=None):
    p=evidence();raw={x['id']:x for x in p['records']}
    grants={
        'EDR_100t':CreatedMinionGrant(attack=3,keywords=(Keyword.LIFESTEAL,)),
        'EDR_100t1':CreatedMinionGrant(attack=2,health=2,keywords=(Keyword.ELUSIVE,)),
        'EDR_100t2':CreatedMinionGrant(attack=-2),
        'EDR_100t3':CreatedMinionGrant(health=4,keywords=(Keyword.TAUNT,)),
        'EDR_100t6':CreatedMinionGrant(keywords=(Keyword.CHARGE,)),
        'EDR_100t9':CreatedMinionGrant(keywords=(Keyword.REBORN,),reborn_policy='full_health_enchantments'),
        'EDR_100t13':CreatedMinionGrant(keywords=(Keyword.DIVINE_SHIELD,Keyword.WINDFURY)),
    }
    ids=tuple(p['implemented_recipes']) if ids is None else ids
    for cid in ids:
        if cid not in grants:raise ValueError('Unsupported real Dark Gift body: '+cid)
    return tuple(DiscoveryMinionGift(cid,raw[cid]['name'],grants[cid],
        cost_delta=-2 if cid=='EDR_100t2' else 0,min_attack=3 if cid=='EDR_100t2' else 0) for cid in ids)


def registry(ids=NEW):
    r=Registry('dark-gift-keyword-recipes-independent-v1');raw={x['id']:x for x in evidence()['records']}
    r.register_card(CardDefinition('dgk.hero','Diagnostic mage',CardType.HERO,health=30,
        metadata=CardMetadata(False,(CardClass.MAGE,),None)))
    for cid in (*MINIONS,'CS2_120'):
        x=raw[cid];card=CardDefinition(cid,x['name'],CardType.MINION,cost=x['cost'],attack=x['attack'],
            health=x['health'],keywords=(Keyword.TAUNT,) if x['tags'].get('TAUNT') else (),metadata=metadata_from_record(x))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    r.register_pool(PoolDefinition('dgk.minions','experimental-v1',CONTEXT.target_id,CONTEXT.mode,
        tuple(PoolMember(x) for x in MINIONS)))
    gifts=DiscoveryGiftPool('dgk.gifts','seven-ordinary-recipes-v1',CONTEXT.target_id,CONTEXT.mode,recipes(ids))
    query=PoolQuery(kinds=(CardType.MINION,),min_cost=3,max_cost=3,collectible=True,class_mode='current')
    r.register_behavior('dgk.discover',lambda c:(DiscoverFromPool(c.player_id,'dgk.minions',query,
        source_id=c.source_id,gift_pool=gifts),))
    x=raw[SOURCE];r.register_card(CardDefinition(SOURCE,x['name'],CardType.MINION,cost=x['cost'],attack=x['attack'],
        health=x['health'],metadata=metadata_from_record(x),battlecry='dgk.discover'))
    r.register_behavior('dgk.scratch',lambda c:(Damage(c.target_id,1),))
    r.register_card(CardDefinition('dgk.damage','Ordinary targeted damage diagnostic',CardType.SPELL,
        on_play='dgk.scratch',requires_target=True))
    return r


class DarkGiftKeywordRecipeTests(unittest.TestCase):
    def game(self,ids=NEW,hand=(SOURCE,),enemy=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('dgk.hero',hand=hand,deck=('CS2_120',)*8,mana=10,max_mana=10),
            PlayerSetup('dgk.hero',board=enemy,deck=('CS2_120',)*8,mana=10,max_mana=10)),
            seed=116,generation_context=CONTEXT),registry(ids))
    def play(self,g,cid=SOURCE,target=None):
        p=g.state.active_player;eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,eid,target));return eid
    def choose(self,g,gift=None):
        option=next(o for o in g._frame.options if gift is None or o.effects[0].selection.gift.id==gift)
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(option.id,)))
        eid=next(e.target_id for e in reversed(g.events) if e.kind=='card_created')
        return eid,option
    def portable(self,g,ids=NEW):
        saved=json.loads(json.dumps(g.snapshot()))
        for other in (Game.from_snapshot(saved,registry(ids)),g.clone(),replay(build_replay(g),registry(ids))):
            self.assertEqual(other.snapshot(),saved)
        return saved
    def rejected(self,g,action):
        saved=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(action)
        self.assertEqual(g.snapshot(),saved)
    def hero(self,g,p=2):return g.state.entities[g.state.players[p].hero_id]

    def test_complete_raw_inventory_is_kept_and_unknown_five_are_not_filtered(self):
        p=evidence()
        self.assertEqual((len(p['records']),len(p['all_local_gift_faces']),len(p['implemented_recipes'])),(33,12,7))
        self.assertEqual(set(p['new_recipes']),set(NEW))
        self.assertEqual(set(p['unsupported_recipe_faces']),{'EDR_100t4','EDR_100t5','EDR_100t7','EDR_100t8','EDR_100t10'})
        for key in ('current_formal_pool_verified','whole_dark_gift_implemented','CN_calibrated'):self.assertFalse(p[key])
        with self.assertRaisesRegex(ValueError,'Unsupported real'):recipes(tuple(p['all_local_gift_faces']))

    def test_native_source_freezes_three_new_recipes_with_printed_previews(self):
        g=self.game();source=self.play(g);self.portable(g)
        options=g._frame.options
        self.assertEqual({o.effects[0].selection.gift.id for o in options},set(NEW))
        self.assertEqual({o.card_id for o in options},set(MINIONS))
        for option in options:
            gift=option.effects[0].selection.gift;card=g.registry.card(option.card_id)
            if gift.id=='EDR_100t1':
                self.assertEqual((option.preview.attack,option.preview.max_health),(card.attack+2,card.health+2))
                self.assertIn(Keyword.ELUSIVE,option.preview.keywords)
            elif gift.id=='EDR_100t6':self.assertIn(Keyword.CHARGE,option.preview.keywords)
            else:self.assertTrue({Keyword.DIVINE_SHIELD,Keyword.WINDFURY}.issubset(option.preview.keywords))
        self.assertEqual(g.state.players[1].mana,8)
        self.assertEqual(g.state.pending_choice.source_id,source)

    def test_well_rested_modifies_stats_blocks_spells_and_allows_combat(self):
        g=self.game(hand=(SOURCE,'dgk.damage'),enemy=('CS2_120',));self.play(g)
        eid,option=self.choose(g,'EDR_100t1');self.play(g,option.card_id)
        e=g.state.entities[eid];printed=g.registry.card(e.card_id)
        self.assertEqual((e.attack,e.max_health),(printed.attack+2,printed.health+2))
        self.assertIn(Keyword.ELUSIVE,e.keywords)
        spell=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id=='dgk.damage')
        self.rejected(g,PlayCard(1,spell,eid))
        g.apply(EndTurn(1));attacker=g.state.players[2].board[0];before=g.state.entities[eid].health
        g.apply(Attack(2,attacker,eid));self.assertEqual(g.state.entities[eid].health,before-2)
        self.portable(g)

    def test_sleepwalker_can_attack_hero_immediately_after_play_and_only_once(self):
        g=self.game();source=self.play(g);eid,option=self.choose(g,'EDR_100t6')
        self.play(g,option.card_id);e=g.state.entities[eid];before=self.hero(g).health
        g.apply(Attack(1,eid,self.hero(g).id))
        self.assertEqual(self.hero(g).health,before-e.attack)
        self.rejected(g,Attack(1,eid,self.hero(g).id))
        self.assertEqual(g.state.players[1].mana,5)
        self.assertTrue(any(a.source_id==source and a.label.endswith('EDR_100t6') for a in e.enchantments))
        self.assertEqual(len(g.state.battlecry_history),1)
        self.portable(g)

    def test_harpy_talons_shield_blocks_one_hit_and_windfury_allows_two_attacks(self):
        g=self.game(hand=(SOURCE,'dgk.damage','dgk.damage'));self.play(g);eid,option=self.choose(g,'EDR_100t13')
        self.play(g,option.card_id);initial=g.state.entities[eid].health
        self.play(g,'dgk.damage',eid)
        self.assertEqual(g.state.entities[eid].health,initial)
        self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[eid].keywords)
        self.assertIn(Keyword.WINDFURY,g.state.entities[eid].keywords)
        # A one-health Magma Rager can be offered. Avoid destroying it with
        # the next diagnostic hit; the shield's one-hit consumption is proven.
        if initial>1:
            self.play(g,'dgk.damage',eid);self.assertEqual(g.state.entities[eid].health,initial-1)
        g.apply(EndTurn(1));g.apply(EndTurn(2));before=self.hero(g).health;attack=g.state.entities[eid].attack
        g.apply(Attack(1,eid,self.hero(g).id));g.apply(Attack(1,eid,self.hero(g).id))
        self.assertEqual(self.hero(g).health,before-2*attack)
        self.rejected(g,Attack(1,eid,self.hero(g).id));self.portable(g)

    def test_all_seven_recipes_can_use_same_discovery_contract_without_new_schema(self):
        g=self.game(ids=None);self.play(g);self.portable(g,ids=None)
        spec=g._frame.options[0].effects[0].batch.spec
        self.assertEqual(len(spec.gift_pool.members),7);self.assertFalse(spec.gift_pool.complete)
        eid,option=self.choose(g);e=g.state.entities[eid]
        self.assertEqual((e.cost,e.attack,e.max_health),(option.preview.cost,option.preview.attack,option.preview.max_health))
        self.assertEqual(g.snapshot()['schema_version'],265)
        self.portable(g,ids=None)

    def test_waiting_resume_keeps_new_binding_random_state_and_one_payment(self):
        g=self.game();self.play(g);saved=g.snapshot();rng=saved['rng_state']
        option=g._frame.options[0];eid,_=self.choose(g,option.effects[0].selection.gift.id)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(g.state.players[1].mana,8)
        other=Game.from_snapshot(saved,registry());self.choose(other,option.effects[0].selection.gift.id)
        self.assertEqual(other.snapshot(),g.snapshot())
        self.assertEqual(len([e for e in g.events if e.kind=='card_created' and e.target_id==eid]),1)

    def test_public_offers_and_delivered_stats_hide_private_gift_receipts_for_both_seats(self):
        g=self.game();self.play(g);own=g.for_player(1).legal_actions();enemy=g.for_player(2).legal_actions()
        self.assertTrue(all('preview' in x for x in own['observation']['pending_choice']['options']))
        for cid in MINIONS:self.assertNotIn(cid,json.dumps(enemy,ensure_ascii=False))
        self.choose(g)
        for seat in (1,2):
            port=g.for_player(seat);wire=json.dumps((port.observe(),port.legal_actions(),port.events()),ensure_ascii=False)
            for field in ('offered_gifts','DiscoveryGiftPool','pool_discovery_picked','"receipt"','resolution_frame'):
                self.assertNotIn(field,wire)

