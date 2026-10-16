"""Real equipment, current turn Attack and physical highest stored-cost draws."""
import json,unittest
from dataclasses import replace
from random import Random
from hs_sim.cards import build_registry
from hs_sim.cards.native_weapon_turn_draw_cards import load_batch
from hs_sim.engine import (Attack,CardDefinition,CardType,CostSpec,EndTurn,Game,Keyword,PlayCard,
    PlayerSetup,Scenario,SelectChoice,SnapshotError,StatRelationLayer,StatRelationOperand,StatRelationSpec,TriggerSpec,Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.dormancy import AwakenMinion,MakeDormant
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,CopyMinion,Damage,Destroy,
    GainArmor,GainResource,InvokeBehavior,ModifyCost,RequestChoice,ReturnToHand,SetStats,Silence,SpendResource,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass,CardMetadata,PlayerCorpseSpendCostSpec,Rarity,Resource,Runes
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.stat_relations import GrantStatRelation
from hs_sim.engine.turn_scheduling import QueueTurns,SkipTurns
from hs_sim.engine.zones import DrawMatching
from hs_sim.engine.pools import PoolQuery
from hs_sim.targets import canonical_digest
import test_player_corpse_spend_cost_basics as corpse_fixtures

BLADE='CORE_BT_921';ASH='RLK_067';TAR='CORE_UNG_928';TAELAN='CS3_024';YETI='CORE_CS2_182'
GIANT='RLK_744'
TURN=StatRelationSpec(operand=StatRelationOperand.CONTROLLER_OPPONENT_TURN,layer=StatRelationLayer.CONDITIONAL_ATTACK,amount=2)


def registry():
    r=build_registry()
    for cid,cost in(('small',2),('large',7),('twin',7)):
        r.register_card(CardDefinition('k33.'+cid,cid,CardType.MINION,cost=cost,attack=1,health=5))
    # A real historical Stitched Giant is an isolated necessary cost-basis witness.
    # Its existing complete support pin is not a new Standard production root.
    giant=corpse_fixtures.evidence()
    r.register_card(CardDefinition(GIANT,giant['name'],CardType.MINION,cost=giant['cost'],attack=giant['attack'],health=giant['health'],
        player_corpse_spend_cost=PlayerCorpseSpendCostSpec(),metadata=CardMetadata(True,(CardClass.DEATH_KNIGHT,),Rarity.EPIC,
            runes=Runes(unholy=1),tribes=('undead',))))
    r.register_card(CardDefinition('k33.shield','Shield target',CardType.MINION,health=5,keywords=(Keyword.DIVINE_SHIELD,)))
    def lower(c):return(ModifyCost(c.state.players[c.player_id].deck[0],CostSpec(set_to=0),c.source_id),)
    def highest(c):return(DrawMatching(c.player_id,PoolQuery(kinds=(CardType.MINION,)),'skip',selection='highest_cost',source_id=c.source_id),)
    scripts=dict(kill=lambda c:(Destroy(c.target_id,c.source_id),),killall=lambda c:tuple(Destroy(i,c.source_id)for i in c.state.players[c.player_id].board),
        lower=lower,highest=highest,hurt=lambda c:(Damage(c.state.players[c.player_id].hero_id,8,c.source_id),),
        set=lambda c:(SetStats(c.target_id,attack=5,source_id=c.source_id),),
        silence=lambda c:(Silence(c.target_id),),copy=lambda c:(CopyMinion(c.target_id,3-c.player_id),),
        control=lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        bounce=lambda c:(ReturnToHand(c.target_id,to_owner=True),),
        transform=lambda c:(Transform(c.target_id,'k33.small'),),into=lambda c:(Transform(c.target_id,TAR),),
        sleep=lambda c:(MakeDormant(c.target_id,None,c.source_id),),awake=lambda c:(AwakenMinion(next(i for p in(1,2)
            for i in c.state.players[p].board if c.state.entities[i].dormancy is not None),c.source_id),),
        extra=lambda c:(QueueTurns((c.player_id,),c.source_id),),skip=lambda c:(SkipTurns(3-c.player_id,1,c.source_id),),
        spend=lambda c:(GainResource(c.player_id,Resource.CORPSES,8),SpendResource(c.player_id,Resource.CORPSES,8)),
        fail=lambda c:(AddToHand(c.player_id,'unknown.k33'),),
        bad_draw=lambda c:(*highest(c),AddToHand(c.player_id,'unknown.k33')))
    targeted={'kill','set','silence','copy','control','bounce','transform','into','sleep'}
    for key,fn in scripts.items():
        r.register_behavior('k33.'+key,fn)
        if key!='fail':r.register_card(CardDefinition('k33.'+key,key,CardType.SPELL,on_play='k33.'+key,requires_target=key in targeted))
    def watch(c):
        if c.event.player_id!=1:return()
        return(RequestChoice(1,(ChoiceOption('ok','Continue',()),
            ChoiceOption('fail','Fail',(InvokeBehavior('k33.fail',c.source_id,1),))),c.source_id),)
    r.register_behavior('k33.watch',watch)
    r.register_card(CardDefinition('k33.watch','Actual draw observer',CardType.MINION,health=8,triggers=(TriggerSpec('card_drawn','k33.watch'),)))
    def start(c):
        ids=[i for p in(1,2)for i in c.state.players[p].board if c.state.entities[i].card_id==TAR]
        return(GainArmor(c.event.player_id,sum(c.state.entities[i].attack for i in ids)),
            RequestChoice(c.event.player_id,(ChoiceOption('ok','Continue turn',()),),c.source_id))
    r.register_behavior('k33.start',start)
    r.register_card(CardDefinition('k33.start','Actual start observer',CardType.MINION,health=8,triggers=(TriggerSpec('turn_started','k33.start'),)))
    return r


class NativeWeaponTurnDrawTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),deck=(YETI,)*8):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=433),self.r)
    def play(self,g,cid,target=None):
        p=g.state.active_player;eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        kind=g.registry.card(cid).kind;g.apply(PlayCard(p,eid,target,len(g.state.players[p].board)if kind==CardType.MINION else None));return eid
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def round(self,g):self.end(g);self.end(g)
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def entity(self,g,cid,p=1):return next(i for i in g.state.players[p].board if g.state.entities[i].card_id==cid)
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));self.assertEqual(Game.from_snapshot(saved,registry()).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for key in('conditional_attack','stat_relation','owner_turn_history','resolution_frame','rng_state'):
                self.assertNotIn('"'+key+'"',public)

    def test_complete_pin_native_keywords_weapon_durability_and_blood_runes(self):
        data=load_batch()
        for row in data['cards']+data['historical_identity_evidence']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        for cid,cost,attack in((BLADE,3,2),(ASH,6,5)):
            card=self.r.card(cid);self.assertEqual((card.cost,card.attack,card.health,card.durability),(cost,attack,0,2))
            self.assertEqual(card.keywords,(Keyword.LIFESTEAL,))
        self.assertEqual(self.r.card(ASH).metadata.runes.blood,2);self.assertEqual(self.r.card(TAR).stat_relations,(TURN,))
        self.assertEqual(set(self.r.card(TAELAN).keywords),{Keyword.TAUNT,Keyword.DIVINE_SHIELD})

    def test_all_four_roots_pay_and_enter_once(self):
        for cid in(BLADE,ASH,TAR,TAELAN):
            g=self.game((cid,));source=self.play(g,cid);self.assertEqual(g.state.players[1].mana,40-self.r.card(cid).cost)
            self.assertEqual(sum(e.kind=='card_played'and e.source_id==source for e in g.events),1)
            self.assertEqual(g.state.entities[source].zone,Zone.WEAPON if cid in(BLADE,ASH)else Zone.BOARD)

    def test_weapon_lifesteal_heals_actual_hero_combat_including_last_durability(self):
        for cid,amount in((BLADE,2),(ASH,5)):
            g=self.game(('k33.hurt',cid));self.play(g,'k33.hurt');self.play(g,cid);wid=g.state.players[1].weapon_id
            g.apply(Attack(1,self.hero(g).id,self.hero(g,2).id));self.assertEqual(self.hero(g).health,22+amount)
            self.assertEqual(g.state.entities[wid].durability,1);self.round(g)
            g.apply(Attack(1,self.hero(g).id,self.hero(g,2).id))
            self.assertEqual(self.hero(g).health,min(30,22+2*amount));self.assertIsNone(g.state.players[1].weapon_id)
            self.assertEqual(g.state.entities[wid].zone,Zone.GRAVEYARD);self.portable(g)

    def test_weapon_lifesteal_does_not_heal_a_shielded_zero_damage_hit(self):
        g=self.game(('k33.hurt',ASH),enemy=('k33.shield',));self.play(g,'k33.hurt');self.play(g,ASH)
        target=self.entity(g,'k33.shield',2);g.apply(Attack(1,self.hero(g).id,target))
        self.assertEqual(self.hero(g).health,22);self.assertEqual(g.state.entities[target].health,5)
        self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[target].keywords)

    def test_tar_tracks_current_turn_without_permanent_accumulation(self):
        g=self.game((TAR,));eid=self.play(g,TAR);self.assertEqual(g.state.entities[eid].attack,1)
        for _ in range(2):
            self.end(g);self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].conditional_attack),(3,2))
            self.end(g);self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].conditional_attack),(1,0))
        self.portable(g)

    def test_tar_control_changes_condition_immediately(self):
        g=self.game(('k33.control',),board=(TAR,));eid=self.entity(g,TAR);self.play(g,'k33.control',eid)
        self.assertEqual((g.state.entities[eid].controller,g.state.entities[eid].attack),(2,3));self.end(g)
        self.assertEqual(g.state.entities[eid].attack,1);self.portable(g)

    def test_tar_numeric_set_is_below_conditional_layer_and_silence_removes_relation(self):
        g=self.game(('k33.set',),board=(TAR,),enemy_hand=('k33.silence',));eid=self.entity(g,TAR);self.play(g,'k33.set',eid)
        self.assertEqual(g.state.entities[eid].attack,5);self.end(g);self.assertEqual(g.state.entities[eid].attack,7)
        self.play(g,'k33.silence',eid);self.assertEqual(g.state.entities[eid].attack,1)
        self.assertNotIn(Keyword.TAUNT,g.state.entities[eid].keywords)

    def test_tar_current_copy_uses_new_controller_turn_not_source_cache(self):
        g=self.game(('k33.copy',),board=(TAR,));eid=self.entity(g,TAR);self.play(g,'k33.copy',eid);new=self.entity(g,TAR,2)
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[new].attack),(1,3));self.end(g)
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[new].attack),(3,1));self.portable(g)

    def test_tar_return_and_transform_do_not_keep_turn_bonus_as_permanent_stats(self):
        g=self.game(board=(TAR,),enemy_hand=('k33.bounce',));eid=self.entity(g,TAR);self.end(g);self.play(g,'k33.bounce',eid)
        self.assertEqual((g.state.entities[eid].zone,g.state.entities[eid].attack,g.state.entities[eid].conditional_attack),(Zone.HAND,1,0))
        self.end(g);self.play(g,TAR);self.assertEqual(g.state.entities[eid].attack,1);self.portable(g)
        g=self.game(('k33.transform','k33.into'),(TAR,));eid=self.entity(g,TAR)
        self.play(g,'k33.transform',eid);self.end(g);self.end(g);self.play(g,'k33.into',eid)
        self.assertEqual(g.state.entities[eid].attack,1);self.end(g);self.assertEqual(g.state.entities[eid].attack,3)

    def test_tar_dormancy_and_awaken_recompute_current_turn(self):
        g=self.game(board=(TAR,),enemy_hand=('k33.sleep','k33.awake'));eid=self.entity(g,TAR);self.end(g)
        self.play(g,'k33.sleep',eid);self.assertEqual(g.state.entities[eid].conditional_attack,0)
        self.play(g,'k33.awake');self.assertEqual(g.state.entities[eid].attack,3);self.portable(g)

    def test_tar_is_current_in_real_start_waiting_context_and_replay(self):
        g=self.game(board=(TAR,'k33.start'));self.end(g);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.hero(g,2).armor,3);self.assertEqual(g.state.entities[self.entity(g,TAR)].attack,3)
        self.portable(g);self.choose(g);self.end(g);self.assertEqual(self.hero(g).armor,1);self.choose(g);self.portable(g)

    def test_tar_extra_turn_and_skipped_opponent_slot_keep_current_controller_turn(self):
        for key in('extra','skip'):
            g=self.game(('k33.'+key,),board=(TAR,));eid=self.entity(g,TAR);self.play(g,'k33.'+key);self.end(g)
            self.assertEqual(g.state.active_player,1);self.assertEqual(g.state.entities[eid].attack,1);self.portable(g)

    def test_tar_death_records_original_opponent_turn_attack(self):
        g=self.game(board=(TAR,),enemy_hand=('k33.kill',));eid=self.entity(g,TAR);self.end(g);self.play(g,'k33.kill',eid)
        dead=next(d for d in g.state.death_history if d.entity_id==eid)
        self.assertEqual(dead.attack,3);self.assertEqual(g.state.entities[eid].conditional_attack,0)
        self.end(g);self.assertEqual(g.state.death_history[-1].attack,3);self.portable(g)

    def test_opponent_turn_spec_rejects_wrong_layer_types_and_dynamic_grants(self):
        for kw in({'amount':0},{'amount':True},{'layer':StatRelationLayer.FINAL_ATTACK},{'card_count':2}):
            with self.assertRaises(ValueError):replace(TURN,**kw)
        with self.assertRaises(ValueError):GrantStatRelation(1,TURN)

    def test_snapshot_rejects_stale_turn_cache_or_duplicate_native_relation(self):
        g=self.game(board=(TAR,));eid=self.entity(g,TAR);self.end(g);saved=g.snapshot()
        for change in('cache','duplicate','granted'):
            s=json.loads(json.dumps(saved));row=s['state']['entities'][str(eid)]
            if change=='cache':row['conditional_attack']=0
            else:
                ability=next(a for a in row['abilities']if a['kind']=='stat_relation')
                if change=='granted':ability['origin']='granted'
                else:
                    clone=json.loads(json.dumps(ability));clone['id']=s['state']['next_attachment_id'];s['state']['next_attachment_id']+=1;row['abilities'].append(clone)
            s['state_hash']=canonical_hash(s['state'])
            with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())

    def test_taelan_draws_physical_highest_minion_excluding_more_expensive_other_types(self):
        g=self.game(('k33.kill',),board=(TAELAN,),deck=('k33.small',ASH,'k33.large'))
        original=list(g.state.players[1].deck);self.play(g,'k33.kill',self.entity(g,TAELAN))
        self.assertEqual(g.state.draw_history[-1].entity_id,original[-1]);self.assertEqual(g.state.players[1].deck,original[:-1]);self.portable(g)

    def test_highest_draw_unique_maximum_uses_no_rng(self):
        g=self.game(('k33.highest',),deck=('k33.small','k33.large'));rng=g.snapshot()['rng_state'];self.play(g,'k33.highest')
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(g.state.draw_history[-1].card_id,'k33.large')

    def test_highest_draw_ties_weight_each_physical_card(self):
        g=self.game(('k33.highest',),deck=('k33.large','k33.large','k33.twin'));ids=g.state.players[1].deck[:]
        s=g.snapshot()['rng_state'];rng=Random();rng.setstate((s[0],tuple(s[1]),s[2]));chosen=rng.choice(ids)
        self.play(g,'k33.highest');self.assertEqual(g.state.draw_history[-1].entity_id,chosen)

    def test_taelan_compares_actual_deck_enchantment_cost(self):
        g=self.game(('k33.lower','k33.kill'),(TAELAN,),deck=('k33.large','k33.small'))
        self.play(g,'k33.lower');self.play(g,'k33.kill',self.entity(g,TAELAN))
        self.assertEqual(g.state.draw_history[-1].card_id,'k33.small')

    def test_taelan_does_not_apply_prospective_hand_intrinsic_discount_in_deck(self):
        g=self.game(('k33.spend','k33.kill'),(TAELAN,),deck=(GIANT,'k33.large'));giant=g.state.players[1].deck[0]
        self.play(g,'k33.spend')
        self.assertEqual(quote_cost(g.state,self.r,g.state.entities[giant]).amount,1)
        self.play(g,'k33.kill',self.entity(g,TAELAN));self.assertEqual(g.state.draw_history[-1].entity_id,giant)
        self.assertEqual(quote_cost(g.state,self.r,g.state.entities[giant]).amount,1)

    def test_taelan_empty_or_no_minion_pool_skips_without_fatigue_or_rng(self):
        for deck in((),('k33.highest',ASH)):
            g=self.game(('k33.kill',),(TAELAN,),deck=deck);rng=g.snapshot()['rng_state'];self.play(g,'k33.kill',self.entity(g,TAELAN))
            self.assertFalse(g.state.draw_history);self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(self.hero(g).health,30)

    def test_taelan_full_hand_preserves_actual_draw_burn_without_replacement(self):
        g=self.game((YETI,)*10,(TAELAN,),enemy_hand=('k33.kill',),deck=('k33.large','k33.small'))
        self.end(g);self.play(g,'k33.kill',self.entity(g,TAELAN));row=g.state.draw_history[-1]
        self.assertEqual((row.player_id,row.card_id,row.outcome),(1,'k33.large','burned'))
        self.assertEqual(g.state.entities[row.entity_id].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.players[1].deck),1)

    def test_taelan_actual_draw_waiting_failure_keeps_original_selection_and_death(self):
        g=self.game(('k33.kill',),(TAELAN,'k33.watch'),deck=('k33.large','k33.twin'))
        self.play(g,'k33.kill',self.entity(g,TAELAN));self.assertIsNotNone(g.state.pending_choice);saved=g.snapshot();selected=g.state.draw_history[-1].entity_id
        self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.assertEqual(g.state.draw_history[-1].entity_id,selected);self.portable(g)

    def test_two_taelan_deaths_query_remaining_deck_separately(self):
        g=self.game(('k33.killall',),(TAELAN,TAELAN),deck=(GIANT,'k33.large','k33.small'))
        self.play(g,'k33.killall');self.assertEqual([d.card_id for d in g.state.draw_history],[GIANT,'k33.large']);self.portable(g)

    def test_highest_draw_transaction_failure_restores_rng_and_original_physical_deck(self):
        g=self.game(('k33.bad_draw',),deck=('k33.large','k33.twin'));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'k33.bad_draw')
        self.assertEqual(g.snapshot(),saved)

    def test_highest_draw_uses_original_typed_codec_and_rejects_unknown_policies(self):
        g=self.game();codec=FrameCodec(g.mechanics,self.r,origin_state=g.state)
        effect=DrawMatching(1,PoolQuery(kinds=(CardType.MINION,)),'skip',selection='highest_cost')
        self.assertEqual(codec.decode(codec.encode(effect)),effect)
        lowest=DrawMatching(1,PoolQuery(),'skip',selection='lowest_cost')
        self.assertEqual(codec.decode(codec.encode(lowest)),lowest)
        for selection in('invented',None,True):
            with self.assertRaises(ValueError):DrawMatching(1,PoolQuery(),'skip',selection=selection)


if __name__=='__main__':unittest.main()
