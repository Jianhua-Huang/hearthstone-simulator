"""P11 native deck destruction, equipped gift condition, escape and death copies."""
from dataclasses import replace
import json,re,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_native_p11_cards import BLACKHORN,CINDERSWORD,ESCAPE,CHARITY,ROOTS,load_batch,register_simple_native_p11_cards
from hs_sim.engine import Attack,CardClass,CardDefinition,CardMetadata,CardType,CostSpec,EndTurn,Game,Keyword,LaunchStarship,PlayCard,PlayerSetup,Scenario,SelectChoice,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.dark_gifts import GrantDarkGift,public_gifts
from hs_sim.engine.effects import AddCostModifier,AddToHand,Buff,ChangeControl,ChoiceOption,Damage,Destroy,EquipWeapon,InvokeBehavior,RequestChoice,ReturnToHand,Transform
from hs_sim.engine.model import Resource
from hs_sim.engine.resolver import CombatDamage
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.starships import construction
from hs_sim.engine.summon_sources import DeathQuery,death_candidates
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import AddToDeck,CardReference,ModifyStoredCost
from hs_sim.targets import canonical_digest
TEST='p11.test.';YETI='CORE_CS2_182';META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def registry():
    r=build_registry();present=tuple(cid in r.cards for cid in ROOTS)
    if any(present)and not all(present):raise AssertionError('Partial P11 registration')
    if not all(present):register_simple_native_p11_cards(r)
    def wait(c,extra=()):return(RequestChoice(c.player_id,(
        ChoiceOption('ok','Continue',()),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,c.player_id),)),*extra,
    ),c.source_id),)
    def reenter(c):return(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,cause=SummonCause.capture(c)),)
    def draw_wait(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id!=ESCAPE:return ()
        return wait(c,(
            ChoiceOption('bounce','Return and reenter old attacker',(ReturnToHand(source.id),InvokeBehavior(TEST+'reenter',c.source_id,c.player_id,source.id))),
            ChoiceOption('change','Transform old attacker',(Transform(source.id,TEST+'low'),)),
            ChoiceOption('control','Give old attacker to opponent',(ChangeControl(source.id,2),)),
        ))
    def deck_wait(c):
        if c.event.player_id!=1 or c.state.entities[c.event.target_id].card_id!=TEST+'low':return ()
        return wait(c,(ChoiceOption('new','Insert cheap card after accepted batch',(AddToDeck(1,TEST+'low',position='bottom',source_id=c.source_id),)),))
    def copy_wait(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id!=CHARITY:return ()
        copies=[e for e in c.state.entities.values()if e.controller==c.player_id and e.zone==Zone.HAND and e.origin_entity_id is not None]
        return wait(c)if len(copies)==1 else ()
    def replace_weapon(c):
        if c.state.entities[c.event.source_id].card_id!=CINDERSWORD:return ()
        return(EquipWeapon(c.player_id,TEST+'weapon'),)
    def prepare_costs(c):
        high=next(c.state.entities[i]for i in c.state.players[1].deck if c.state.entities[i].card_id==TEST+'high')
        low=next(c.state.entities[i]for i in c.state.players[2].deck if c.state.entities[i].card_id==TEST+'low')
        return(ModifyStoredCost(CardReference.capture(high),CostSpec(delta=-2),c.source_id),ModifyStoredCost(CardReference.capture(low),CostSpec(delta=1),c.source_id))
    scripts={
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'buff':lambda c:(Buff(c.target_id,5,5,c.source_id),),
        'change':lambda c:(Transform(c.target_id,TEST+'high'),),
        'take':lambda c:(ChangeControl(c.target_id,1),),
        'give':lambda c:(ChangeControl(c.target_id,2),),
        'costs':prepare_costs,
        'external':lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-20),source_id=c.source_id),),
        'gift':lambda c:(GrantDarkGift(CardReference.capture(c.state.entities[c.target_id]),'EDR_100t',c.source_id),),
        'deck_gift':lambda c:(GrantDarkGift(CardReference.capture(c.state.entities[c.state.players[1].deck[0]]),'EDR_100t',c.source_id),),
        'fill':lambda c:tuple(AddToHand(c.player_id,YETI,c.source_id)for _ in range(3)),
        'bare_combat':lambda c:(CombatDamage(next(i for i in c.state.players[1].board if c.state.entities[i].card_id==ESCAPE),c.state.players[2].hero_id),),
        'wound':lambda c:(Damage(c.state.players[1].hero_id,29,c.source_id),),
    }
    for name,body in scripts.items():
        key=TEST+name;r.register_behavior(key,body)
        target=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,),relation='friendly')if name=='gift'else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if name in('kill','buff','change','take','give')else None
        r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=META,targeting=target))
    r.register_behavior(TEST+'noop',lambda c:());r.register_behavior(TEST+'fail',lambda c:(AddToHand(c.player_id,'p11.missing'),));r.register_behavior(TEST+'reenter',reenter)
    for name,cost,attack,health in(('low',2,2,3),('high',4,3,5),('weak',1,1,2)):
        r.register_card(CardDefinition(TEST+name,name,CardType.MINION,cost=cost,attack=attack,health=health,metadata=META))
    r.register_card(CardDefinition(TEST+'death','Deathrattle fixture',CardType.MINION,cost=2,attack=1,health=2,deathrattle=TEST+'noop',metadata=META))
    r.register_card(CardDefinition(TEST+'cheap_spell','Spell',CardType.SPELL,cost=2,on_play=TEST+'noop',metadata=META))
    r.register_card(CardDefinition(TEST+'weapon','Weapon',CardType.WEAPON,cost=1,attack=2,durability=2,metadata=META))
    r.register_card(CardDefinition(TEST+'location','Location',CardType.LOCATION,cost=2,durability=2,on_use=TEST+'noop',metadata=META))
    for name,event,body in(('draw_wait','card_drawn',draw_wait),('deck_wait','card_destroyed_in_deck',deck_wait),
                            ('copy_wait','card_added_to_hand',copy_wait),('replace_weapon','weapon_equipped',replace_weapon)):
        key=TEST+name;r.register_behavior(key,body)
        r.register_card(CardDefinition(key,name,CardType.MINION,health=9,metadata=META,triggers=(TriggerSpec(event,key),)))
    r.validate();return r

class SimpleNativeP11CardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),*,deck=(YETI,)*12,enemy_deck=(YETI,)*12,enemy_hand=(),active=1):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=enemy_deck,mana=40,max_mana=40,mana_cap=40),
        ),active_player=active,seed=1111),self.r)
    def entities(self,g,cid,p=1,zone='board'):return[g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid]
    def first(self,g,cid,p=1,zone='board'):return self.entities(g,cid,p,zone)[0]
    def play(self,g,cid,target=None):
        p=g.state.active_player;eid=self.first(g,cid,p,'hand').id
        g.apply(PlayCard(p,eid,target,len(g.state.players[p].board)if self.r.card(cid).kind==CardType.MINION else None));return eid
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def cycle(self,g):self.end(g);self.end(g)
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def copies(self,g):return[g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].origin_entity_id is not None]
    def attack(self,g,target=None):
        source=self.first(g,ESCAPE).id;g.apply(Attack(1,source,target or g.state.players[2].hero_id));return source
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry());self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','MinionReference','CardReference','components_material','behavior_id'):
                self.assertNotIn(key,public)
        return other

    def test_complete_raw_pins_official_faces_and_metadata(self):
        d=load_batch();self.assertEqual(tuple(x['record']['id']for x in d['cards']),ROOTS);self.assertEqual(len(d['official_observations']['observations']),8)
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['skipped'])
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']:
            raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(self.r.card(raw['id']).metadata,replace(metadata_from_record(raw),deck_identity=raw['id']))
            for o in(o for o in d['official_observations']['observations']if o['card_id']==raw['id']):
                f=o['face'];en=o['locale']=='en-us';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']))
                self.assertEqual((f['id'],f['manaCost'],f['cardTypeId'],f['cardSetId']),(raw['dbf_id'],raw['cost'],raw['tags']['CARDTYPE'],raw['card_set_id']))
        self.assertIsNone(self.r.card(CHARITY).spell_school);self.assertEqual(self.r.card(CINDERSWORD).durability,2)

    def test_default_311_and_fingerprint_unchanged(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')

    def test_blackhorn_both_decks_all_card_types_single_batch_not_death_or_discard(self):
        cards=(TEST+'low',TEST+'cheap_spell',TEST+'weapon',TEST+'location',TEST+'high')
        g=self.game((BLACKHORN,),deck=cards,enemy_deck=cards);self.play(g,BLACKHORN)
        for p in(1,2):self.assertEqual([g.state.entities[i].card_id for i in g.state.players[p].deck],[TEST+'high'])
        self.assertEqual(sum(e.kind=='card_destroyed_in_deck'for e in g.events),8);self.assertFalse(g.state.death_history)
        self.assertFalse(any(e.kind=='card_discarded'for e in g.events));self.assertEqual(g.state.players[1].mana,33);self.portable(g)

    def test_blackhorn_stored_current_cost_not_printed_cost_or_external_hand_quote(self):
        g=self.game((TEST+'costs',TEST+'external',BLACKHORN),deck=(TEST+'high',TEST+'low'),enemy_deck=(TEST+'high',TEST+'low'))
        self.play(g,TEST+'costs');self.play(g,TEST+'external');self.play(g,BLACKHORN)
        self.assertFalse(g.state.players[1].deck);self.assertEqual([g.state.entities[i].card_id for i in g.state.players[2].deck],[TEST+'high',TEST+'low'])

    def test_blackhorn_all_selected_moved_before_first_observer_no_requery_for_new_cheap(self):
        g=self.game((BLACKHORN,),(TEST+'deck_wait',),deck=(TEST+'low',TEST+'high'),enemy_deck=(TEST+'low',TEST+'high'))
        self.play(g,BLACKHORN);self.assertIsNotNone(g.state.pending_choice)
        for p in(1,2):self.assertEqual([g.state.entities[i].card_id for i in g.state.players[p].deck],[TEST+'high'])
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'new');self.choose(other,'new');self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],[TEST+'high',TEST+'low']);self.portable(g)

    def test_blackhorn_empty_decks_no_fatigue_or_rng(self):
        g=self.game((BLACKHORN,),deck=(),enemy_deck=());rng=g._rng.getstate();self.play(g,BLACKHORN)
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)

    def test_sword_without_gift_keeps_printed_one_attack_two_durability(self):
        g=self.game((CINDERSWORD,TEST+'low'));source=self.play(g,CINDERSWORD);e=g.state.entities[source]
        self.assertEqual((e.attack,e.durability,g.state.players[1].mana),(1,2,39));self.portable(g)

    def test_sword_actual_dark_gift_in_current_hand_grants_three_attack_only(self):
        g=self.game((TEST+'gift',TEST+'low',CINDERSWORD));target=self.first(g,TEST+'low',zone='hand').id
        self.play(g,TEST+'gift',target);self.assertTrue(public_gifts(g.state.entities[target]));source=self.play(g,CINDERSWORD)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].durability),(4,2));self.portable(g)

    def test_sword_gift_in_deck_or_on_board_does_not_meet_holding(self):
        for zone in('deck','board'):
            with self.subTest(zone=zone):
                gift=TEST+('deck_gift'if zone=='deck'else'gift')
                g=self.game((gift,CINDERSWORD,TEST+'low'),deck=(TEST+'low',YETI))
                target=None if zone=='deck'else self.first(g,TEST+'low',zone='hand').id;self.play(g,gift,target)
                if zone=='board':self.play(g,TEST+'low')
                source=self.play(g,CINDERSWORD);self.assertEqual(g.state.entities[source].attack,1)

    def test_sword_original_weapon_replaced_before_body_does_not_buff_replacement(self):
        g=self.game((TEST+'gift',TEST+'low',CINDERSWORD),(TEST+'replace_weapon',));target=self.first(g,TEST+'low',zone='hand').id
        self.play(g,TEST+'gift',target);source=self.play(g,CINDERSWORD)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);weapon=g.state.entities[g.state.players[1].weapon_id]
        self.assertEqual((weapon.card_id,weapon.attack,weapon.durability),(TEST+'weapon',2,2));self.portable(g)

    def test_sword_repeated_actual_battlecry_applies_each_original_weapon_reward(self):
        g=self.game((TEST+'gift',TEST+'low',CINDERSWORD),('TIME_064',));self.play(g,TEST+'gift',self.first(g,TEST+'low',zone='hand').id)
        source=self.play(g,CINDERSWORD);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].durability),(7,2))

    def test_escape_completed_surviving_attack_draws_then_removes_without_own_death(self):
        g=self.game(board=(ESCAPE,),enemy=(TEST+'weak',));source=self.attack(g,self.first(g,TEST+'weak',2).id)
        self.assertEqual(g.state.entities[source].zone,Zone.SETASIDE);self.assertEqual(len(g.state.players[1].hand),1)
        self.assertFalse(any(d.entity_id==source for d in g.state.death_history));self.assertEqual(g.state.players[1].resources[Resource.CORPSES],0)
        events=[e for e in g.events if e.source_id==source];self.assertLess(next(e.sequence for e in events if e.kind=='card_drawn'),next(e.sequence for e in events if e.kind=='cards_removed_from_game'));self.portable(g)

    def test_escape_attack_hero_also_qualifies_but_dying_attacker_does_not(self):
        g=self.game(board=(ESCAPE,));source=self.attack(g);self.assertEqual(g.state.entities[source].zone,Zone.SETASIDE)
        g=self.game(board=(ESCAPE,),enemy=(YETI,));source=self.attack(g,self.first(g,YETI,2).id)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertFalse(g.state.players[1].hand)

    def test_escape_defending_other_attacker_and_bare_combat_are_not_self_attack_credit(self):
        g=self.game(board=(ESCAPE,),enemy=(TEST+'weak',),active=2);source=self.first(g,ESCAPE).id
        g.apply(Attack(2,self.first(g,TEST+'weak',2).id,source));self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.assertFalse(g.state.players[1].hand)
        g=self.game((TEST+'bare_combat',),(ESCAPE,));self.play(g,TEST+'bare_combat');self.assertEqual(self.first(g,ESCAPE).zone,Zone.BOARD)

    def test_escape_full_hand_burn_and_nonlethal_fatigue_still_remove_source(self):
        g=self.game((YETI,)*10,(ESCAPE,));source=self.attack(g);self.assertEqual(g.state.entities[source].zone,Zone.SETASIDE);self.assertEqual(len(g.state.players[1].hand),10)
        g=self.game(board=(ESCAPE,),deck=());source=self.attack(g);self.assertEqual(g.state.entities[source].zone,Zone.SETASIDE);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,29)

    def test_escape_draw_wait_restores_rolls_back_and_same_id_reentry_is_not_removed(self):
        g=self.game(board=(ESCAPE,TEST+'draw_wait'));source=self.attack(g);presence=g.state.entities[source].board_presence_id
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'bounce');self.choose(other,'bounce');self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.assertNotEqual(g.state.entities[source].board_presence_id,presence);self.assertEqual(len(g.state.players[1].hand),1);self.portable(g)

    def test_escape_draw_reaction_transform_or_control_invalidates_old_removal(self):
        for branch in('change','control'):
            with self.subTest(branch=branch):
                g=self.game(board=(ESCAPE,TEST+'draw_wait'));source=self.attack(g);self.choose(g,branch)
                self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.assertEqual(g.state.entities[source].controller,2 if branch=='control'else 1)

    def test_escape_fatigue_terminal_stops_later_removal(self):
        g=self.game((TEST+'wound',),(ESCAPE,),deck=());self.play(g,TEST+'wound');source=self.attack(g)
        self.assertEqual(g.state.winner,2);self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.portable(g)

    def test_charity_creates_new_base_death_copy_plus_three_without_old_local_buff_or_injury(self):
        g=self.game((TEST+'buff',TEST+'kill',CHARITY),(TEST+'low',));source=self.first(g,TEST+'low').id
        self.play(g,TEST+'buff',source);self.play(g,TEST+'kill',source);self.play(g,CHARITY);copy,=self.copies(g)
        self.assertNotEqual(copy.id,source);self.assertEqual(copy.origin_entity_id,source)
        self.assertEqual((copy.card_id,copy.attack,copy.health),(TEST+'low',5,6));self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.portable(g)

    def test_charity_current_death_form_and_each_distinct_occurrence_keep_order(self):
        g=self.game((TEST+'change',TEST+'kill',TEST+'kill',CHARITY),(TEST+'low',TEST+'low'));first,second=[e.id for e in self.entities(g,TEST+'low')]
        self.play(g,TEST+'change',first);self.play(g,TEST+'kill',first);self.play(g,TEST+'kill',second);self.play(g,CHARITY)
        self.assertEqual([(e.card_id,e.attack,e.health)for e in self.copies(g)],[(TEST+'high',6,8),(TEST+'low',5,6)]);self.portable(g)

    def test_charity_friendly_is_controller_at_death_not_original_owner(self):
        g=self.game((TEST+'give',TEST+'take',TEST+'kill',TEST+'kill',CHARITY),(TEST+'low',),enemy=(TEST+'high',))
        own=self.first(g,TEST+'low').id;enemy=self.first(g,TEST+'high',2).id
        self.play(g,TEST+'give',own);self.play(g,TEST+'take',enemy);self.play(g,TEST+'kill',own);self.play(g,TEST+'kill',enemy);self.play(g,CHARITY)
        copy,=self.copies(g);self.assertEqual((copy.card_id,copy.owner,copy.controller),(TEST+'high',1,1));self.assertEqual(copy.origin_entity_id,enemy)

    def test_charity_previous_global_turn_is_excluded_and_empty_pool_does_not_fatigue(self):
        g=self.game((TEST+'kill',CHARITY),(TEST+'low',));self.play(g,TEST+'kill',self.first(g,TEST+'low').id);self.cycle(g)
        before=len(g.state.players[1].deck);self.play(g,CHARITY);self.assertFalse(self.copies(g));self.assertEqual(len(g.state.players[1].deck),before)

    def test_charity_native_death_query_never_deduplicates_same_entity_occurrences(self):
        g=self.game((TEST+'kill',),(TEST+'low',));self.play(g,TEST+'kill',self.first(g,TEST+'low').id);state=g.state;original=state.death_history[0]
        state.death_history.append(replace(original,id=2,batch=2))
        rows=death_candidates(state,self.r,1,DeathQuery(min_turn=state.turn,max_turn=state.turn));self.assertEqual([r.entity_id for r in rows],[original.entity_id]*2)

    def test_charity_real_launched_starship_death_copy_preserves_components_and_composed_base(self):
        g=self.game((TEST+'kill',TEST+'kill',CHARITY),('SC_403a',));piece=g.state.players[1].board[0];self.play(g,TEST+'kill',piece)
        ship=construction(g.state,1);self.assertIsNotNone(ship);g.apply(LaunchStarship(1,ship.id));source=g.state.entities[ship.id]
        expected=(source.base_attack+3,source.base_health+3);parts=source.components;self.play(g,TEST+'kill',source.id);self.play(g,CHARITY)
        copy=next(e for e in self.copies(g)if e.origin_entity_id==source.id)
        self.assertEqual(copy.components,parts);self.assertEqual((copy.attack,copy.health),expected);self.portable(g)

    def test_charity_first_copy_wait_restores_remaining_original_inventory_once(self):
        g=self.game((TEST+'kill',TEST+'kill',CHARITY),(TEST+'copy_wait',TEST+'low',TEST+'low'))
        targets=[e.id for e in self.entities(g,TEST+'low')]
        for target in targets:self.play(g,TEST+'kill',target)
        self.play(g,CHARITY);self.assertEqual(len(self.copies(g)),1);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.copies(g)),2)

    def test_charity_full_hand_copies_burn_through_original_materialization(self):
        g=self.game((TEST+'kill',TEST+'kill',TEST+'fill',CHARITY,*(YETI,)*6),(TEST+'low',TEST+'low'))
        for target in [e.id for e in self.entities(g,TEST+'low')]:self.play(g,TEST+'kill',target)
        self.play(g,TEST+'fill');self.assertEqual(len(g.state.players[1].hand),10)
        self.play(g,CHARITY);self.assertEqual(len(self.copies(g)),1);self.assertEqual(len(g.state.players[1].hand),10)
        created=[e for e in g.state.entities.values()if e.origin_entity_id is not None]
        self.assertEqual(len(created),2);self.assertEqual(sorted(e.zone for e in created),sorted((Zone.HAND,Zone.GRAVEYARD)))
        self.assertTrue(all((e.attack,e.health)==(5,6)for e in created));self.portable(g)

if __name__=='__main__':unittest.main()
