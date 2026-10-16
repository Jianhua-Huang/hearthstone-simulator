"""Real physical-zone cards, preserved provenance and atomic deck removal."""
from dataclasses import replace
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.physical_zone_cards import load_batch
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,DeckPolicy,DeckSpec,
    Game,Keyword,MatchSetup,OpeningHook,PlayCard,PlayerSetup,Rarity,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.effects import (AddToHand,ChangeManaCrystals,ChoiceOption,Draw,InvokeBehavior,
    RequestChoice,ReturnToHand,Transform)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash,SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.zones import AddToDeck,CardReference,CopyCard,DestroyDeckBatch,DestroyDeckCard,MoveCard
from hs_sim.targets import canonical_digest

DOOM='CORE_EX1_310';CLEAN='CORE_REV_946';MUSTER='CORE_GVG_061';RECRUIT='CS2_101t';WEAPON='CS2_091'
YETI='CORE_CS2_182';TIDE='CORE_EX1_509'


def registry(mode=None,ops=()):
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
    def original(c):
        ids=set(c.state.opening.original_entities[0])
        return next(c.state.entities[i]for i in c.state.players[1].deck if i in ids and c.state.entities[i].card_id==YETI)
    def transform(c,back=False,same=False):
        entity=original(c)
        tail=(InvokeBehavior('k30.back',c.source_id,c.player_id,entity.id),)if back else()
        return(TransformStoredCard(CardReference.capture(entity),YETI if same else TIDE,c.source_id),*tail)
    def back(c):return(TransformStoredCard(CardReference.capture(c.state.entities[c.target_id]),YETI,c.source_id),)
    def add(c,fuel=False):
        return tuple(AddToDeck(pid,'k30.fuel'if fuel else YETI,'top',c.source_id)for pid in(1,2))
    def batch(c,sequential=False):
        refs=tuple(CardReference.capture(c.state.entities[i])for p in(1,2)for i in c.state.players[p].deck)
        return tuple(DestroyDeckCard(ref,c.source_id)for ref in refs)if sequential else(DestroyDeckBatch(refs,c.source_id),)
    def foreign(c):return(MoveCard(CardReference.capture(original(c)),2,Zone.DECK,'top',source_id=c.source_id),)
    def copying(c):return(CopyCard(CardReference.capture(original(c)),1,destination=Zone.DECK,position='bottom',source_id=c.source_id),)
    bodies=dict(add=lambda c:add(c),seed_fuel=lambda c:add(c,True),change=lambda c:transform(c),
        same=lambda c:transform(c,same=True),back_change=lambda c:transform(c,back=True),back=back,
        foreign=foreign,copy=copying,batch=batch,sequential=lambda c:batch(c,True),
        board=lambda c:(Transform(c.target_id,YETI),ReturnToHand(c.target_id,to_owner=True)),
        fail=lambda c:(AddToHand(c.player_id,'unknown.k30'),),
        fail_change=lambda c:(*transform(c),InvokeBehavior('k30.fail',c.source_id,c.player_id)))
    for key,body in bodies.items():
        r.register_behavior('k30.'+key,body)
        if key not in('back','fail'):
            r.register_card(CardDefinition('k30.'+key,key,CardType.SPELL,on_play='k30.'+key,
                requires_target=key=='board',metadata=meta))
    r.register_behavior('k30.draw2',lambda c:(Draw(c.player_id,2,c.source_id),))
    r.register_card(CardDefinition('k30.fuel','Native destruction draw fixture',CardType.SPELL,
        on_destroyed='k30.draw2',metadata=meta))
    r.register_behavior('k30.discard_new',lambda c:(AddToHand(c.player_id,YETI,c.source_id),))
    r.register_card(CardDefinition('k30.discarded','Native discard replacement fixture',CardType.SPELL,
        on_discard='k30.discard_new',metadata=meta))
    def boot(c):
        return(ChangeManaCrystals(c.player_id,10,filled=True),AddToHand(c.player_id,CLEAN,c.source_id),
            *(AddToHand(c.player_id,'k30.'+key,c.source_id)for key in ops))
    r.register_behavior('k30.boot',boot)
    r.register_card(CardDefinition('k30.boot','Opening fixture',CardType.MINION,health=1,
        metadata=replace(meta,collectible=True),opening_hooks=(OpeningHook('after_mulligan','k30.boot'),)))
    if mode:
        def watch(c):
            if mode=='summon'and c.state.entities[c.event.target_id].card_id!=RECRUIT:return ()
            effects=(AddToDeck(1,YETI,'bottom',c.source_id),)if mode=='destroy'else()
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',effects),
                ChoiceOption('fail','Fail',(InvokeBehavior('k30.fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior('k30.watch',watch)
        r.register_card(CardDefinition('k30.watch','Boundary observer',CardType.MINION,health=8,
            triggers=(TriggerSpec('minion_summoned'if mode=='summon'else'card_destroyed_in_deck','k30.watch'),),metadata=meta))
        if mode=='destroy':
            # Install through an ordinary opening effect, not by mutating Game.state.
            from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
            original_boot=boot
            def boot_watch(c):
                extra=(SummonByCard(c.player_id,(SummonEntryMaterial('k30.watch'),),SummonCause.capture(c)),)if c.player_id==1 else()
                return (*original_boot(c),*extra)
            r.register_behavior('k30.boot_watch',boot_watch)
            card=r.card('k30.boot')
            # A separate actual opening card avoids replacing a registered definition.
            r.register_card(replace(card,id='k30.boot_watch',opening_hooks=(OpeningHook('after_mulligan','k30.boot_watch'),)))
    return r


class PhysicalZoneCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),*,board=(),enemy=(),deck=(YETI,)*6,weapon=None,mode=None):
        self.mode=mode;self.ops=()
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,
            hero_power_card_id='HERO_08bp',weapon_card_id=weapon,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*6,hero_power_card_id='HERO_08bp',mana=40,max_mana=40,mana_cap=40)),
            seed=430),registry(mode)if mode else self.r)
    def match(self,ops=(),mode=None):
        self.mode=mode;self.ops=ops;r=registry(mode,ops)
        boot='k30.boot_watch'if mode=='destroy'else'k30.boot'
        policy=DeckPolicy('k30.experimental','k30.fixed-test','experimental',(YETI,boot),deck_size=12,max_copies=12)
        cards=(boot,)+(YETI,)*11
        g=Game.from_decks(MatchSetup(tuple(DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,cards)for _ in(1,2)),
            policy,'GAME_005',seed=430,first_player=1),r)
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        return g
    def eid(self,g,cid,p=1,zone='hand'):
        return next(i for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):g.apply(PlayCard(g.state.active_player,self.eid(g,cid),target))
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));fresh=registry(self.mode,self.ops)
        h=Game.from_snapshot(saved,fresh);self.assertEqual(h.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),fresh).snapshot(),saved)
        for pid in(1,2):
            public=json.dumps(g.observe(pid))+json.dumps(g.for_player(pid).legal_actions())
            for key in('face_replaced','original_entities','resolution_frame','discard_history'):
                self.assertNotIn('"'+key+'"',public)
        return h

    def test_complete_source_pins_identity_and_muster_dependencies(self):
        batch=load_batch();self.assertEqual(len(batch['cards']),4)
        for row in batch['cards']+batch['reused_dependencies']+batch['historical_identity_evidence']:
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual((self.r.card(WEAPON).attack,self.r.card(WEAPON).durability),(1,4))
        self.assertEqual(self.r.card(CLEAN).metadata.deck_identity,'REV_946')
        self.assertEqual(self.r.card(DOOM).metadata.deck_identity,'EX1_310')

    def test_doomguard_paid_entry_discards_two_current_hand_cards_once(self):
        g=self.game((DOOM,YETI,YETI,YETI));self.play(g,DOOM)
        self.assertEqual(len(g.state.players[1].hand),1);self.assertEqual(len(g.state.discard_history),2)
        self.assertEqual(g.state.players[1].mana,35)
        source=self.eid(g,DOOM,zone='board');self.assertIn(Keyword.CHARGE,g.state.entities[source].keywords)
        g.apply(Attack(1,source,g.state.players[2].hero_id));self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,25)
        self.portable(g)

    def test_doomguard_zero_or_one_discard_candidate_has_no_extra_work(self):
        for extra,expected in (((),0),((YETI,),1)):
            g=self.game((DOOM,*extra));self.play(g,DOOM)
            self.assertEqual(len(g.state.discard_history),expected);self.assertEqual(g.state.players[1].hand,[])

    def test_doomguard_requeries_after_native_discard_generated_new_card(self):
        g=self.game((DOOM,'k30.discarded'));self.play(g,DOOM)
        self.assertEqual(len(g.state.discard_history),2);self.assertEqual(g.state.players[1].hand,[])
        self.assertEqual([r.card.card_id for r in g.state.discard_history],['k30.discarded',YETI])

    def test_steamcleaner_without_original_deck_facts_rejects_and_rolls_back(self):
        g=self.game((CLEAN,));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,CLEAN)
        self.assertEqual(g.snapshot(),saved)

    def test_cleaner_removes_generated_same_name_cards_from_both_decks(self):
        g=self.match(('add',));self.play(g,'k30.add');originals={i for group in g.state.opening.original_entities for i in group}
        generated={i for p in(1,2)for i in g.state.players[p].deck if i not in originals}
        self.assertEqual(len(generated),2);before_deaths=len(g.state.death_history);self.play(g,CLEAN)
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in generated))
        self.assertTrue(all(i in originals for p in(1,2)for i in g.state.players[p].deck))
        self.assertEqual(len(g.state.death_history),before_deaths);self.assertEqual(g.state.discard_history,[]);self.portable(g)

    def test_cleaner_protects_original_physical_card_moved_to_opponent_deck(self):
        g=self.match(('foreign',));original=set(g.state.opening.original_entities[0]);self.play(g,'k30.foreign')
        moved=original&set(g.state.players[2].deck);self.assertEqual(len(moved),1);self.play(g,CLEAN)
        self.assertTrue(moved<=set(g.state.players[2].deck));self.portable(g)

    def test_cleaner_protects_unchanged_originals_without_rng_or_fatigue(self):
        g=self.match();before=g.snapshot()['rng_state'];decks=tuple(tuple(g.state.players[p].deck)for p in(1,2))
        self.play(g,CLEAN);self.assertEqual(tuple(tuple(g.state.players[p].deck)for p in(1,2)),decks)
        self.assertEqual(g.snapshot()['rng_state'],before)

    def test_same_face_transform_loses_credit_without_replacing_physical_id(self):
        g=self.match(('same',));before=set(g.state.players[1].deck);self.play(g,'k30.same')
        changed={i for i in before if g.state.entities[i].face_replaced};self.assertEqual(len(changed),1)
        self.assertTrue(changed<=set(g.state.players[1].deck));self.play(g,CLEAN)
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in changed));self.portable(g)

    def test_transform_back_to_starting_name_does_not_restore_credit(self):
        g=self.match(('back_change',));self.play(g,'k30.back_change')
        changed={i for i in g.state.players[1].deck if g.state.entities[i].face_replaced}
        self.assertEqual(len(changed),1);self.assertTrue(all(g.state.entities[i].card_id==YETI for i in changed))
        self.play(g,CLEAN);self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in changed))

    def test_new_copy_keeps_recipient_provenance_and_is_still_outside_originals(self):
        g=self.match(('same','copy'));self.play(g,'k30.same');self.play(g,'k30.copy')
        originals={i for group in g.state.opening.original_entities for i in group}
        copies={i for i in g.state.players[1].deck if i not in originals};self.assertEqual(len(copies),1)
        self.assertTrue(all(not g.state.entities[i].face_replaced for i in copies));self.play(g,CLEAN)
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in copies))

    def test_board_transform_and_normal_return_retain_replacement_marker(self):
        g=self.game(('k30.board',),board=(TIDE,));entity=self.eid(g,TIDE,zone='board')
        self.play(g,'k30.board',entity);self.assertEqual(g.state.entities[entity].zone,Zone.HAND)
        self.assertTrue(g.state.entities[entity].face_replaced);self.portable(g)

    def test_failed_transform_restores_provenance_and_entire_original_action(self):
        g=self.match(('fail_change',));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'k30.fail_change')
        self.assertEqual(g.snapshot(),saved)

    def test_all_batch_targets_removed_before_native_destruction_draws(self):
        g=self.match(('add','seed_fuel'));self.play(g,'k30.add');self.play(g,'k30.seed_fuel')
        originals={i for group in g.state.opening.original_entities for i in group}
        targets={i for p in(1,2)for i in g.state.players[p].deck if i not in originals}
        self.assertEqual(len(targets),4);self.play(g,CLEAN)
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in targets))
        events=[e for e in g.events if e.kind in('card_destroyed_in_deck','card_drawn')]
        last_destroy=max(e.sequence for e in events if e.kind=='card_destroyed_in_deck')
        self.assertTrue(all(e.sequence>last_destroy for e in events if e.kind=='card_drawn'and e.sequence>min(
            x.sequence for x in events if x.kind=='card_destroyed_in_deck')));self.portable(g)

    def test_batch_wait_observes_all_removals_and_does_not_destroy_later_additions(self):
        g=self.match(('add',),mode='destroy');self.play(g,'k30.add')
        originals={i for group in g.state.opening.original_entities for i in group}
        targets={i for p in(1,2)for i in g.state.players[p].deck if i not in originals}
        self.play(g,CLEAN);self.assertIsNotNone(g.state.pending_choice)
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in targets));self.portable(g)
        while g.state.pending_choice:self.choose(g)
        later={i for p in(1,2)for i in g.state.players[p].deck if i not in originals}
        self.assertEqual(len(later),2);self.portable(g)

    def test_batch_failed_choice_preserves_all_removals_original_frame_and_rng(self):
        g=self.match(('add',),mode='destroy');self.play(g,'k30.add');self.play(g,CLEAN);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.portable(g)

    def test_batch_constructor_rejects_duplicate_and_hand_targets(self):
        g=self.game((YETI,));hand=CardReference.capture(g.state.entities[self.eid(g,YETI)])
        with self.assertRaises(ValueError):DestroyDeckBatch((hand,))
        deck=CardReference.capture(g.state.entities[g.state.players[1].deck[0]])
        with self.assertRaises(ValueError):DestroyDeckBatch((deck,deck))
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        effect=DestroyDeckBatch((deck,));self.assertEqual(codec.decode(codec.encode(effect)),effect)

    def test_muster_pays_once_and_equips_named_one_four_after_three_recruits(self):
        g=self.game((MUSTER,));self.play(g,MUSTER)
        self.assertEqual(len(g.state.players[1].board),3);self.assertEqual(g.state.players[1].mana,37)
        self.assertTrue(all(g.state.entities[i].card_id==RECRUIT for i in g.state.players[1].board))
        weapon=g.state.entities[g.state.players[1].weapon_id];self.assertEqual((weapon.card_id,weapon.attack,weapon.durability),(WEAPON,1,4))
        equip=next(e.sequence for e in g.events if e.kind=='weapon_equipped')
        self.assertTrue(all(e.sequence<equip for e in g.events if e.kind=='minion_summoned'));self.portable(g)

    def test_muster_full_or_one_space_board_still_equips_without_rng(self):
        for count in(6,7):
            g=self.game((MUSTER,),board=(YETI,)*count);before=g.snapshot()['rng_state'];self.play(g,MUSTER)
            self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(g.snapshot()['rng_state'],before)
            self.assertEqual(g.state.entities[g.state.players[1].weapon_id].card_id,WEAPON)

    def test_muster_uses_existing_source_quantity_multiplier(self):
        g=self.game((MUSTER,),board=('CORE_DAL_575',));self.play(g,MUSTER)
        self.assertEqual(len(g.state.players[1].board),7)

    def test_muster_waiting_keeps_equipment_after_all_accepted_summons(self):
        g=self.game((MUSTER,),board=('k30.watch',),mode='summon');self.play(g,MUSTER)
        self.assertIsNone(g.state.players[1].weapon_id);self.portable(g)
        count=0
        while g.state.pending_choice:
            self.assertIsNone(g.state.players[1].weapon_id);self.choose(g);count+=1
        self.assertEqual(count,3);self.assertEqual(g.state.entities[g.state.players[1].weapon_id].card_id,WEAPON);self.portable(g)

    def test_muster_weapon_replacement_does_not_refresh_used_hero_attack(self):
        g=self.game((MUSTER,),weapon='CS2_106');hero=g.state.players[1].hero_id;old=g.state.players[1].weapon_id
        g.apply(Attack(1,hero,g.state.players[2].hero_id));self.play(g,MUSTER)
        self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD)
        with self.assertRaises(IllegalAction):g.apply(Attack(1,hero,g.state.players[2].hero_id))

    def test_new_provenance_field_is_strict_and_old_schema_is_rejected(self):
        g=self.game();saved=g.snapshot();self.assertEqual(saved['schema_version'],SNAPSHOT_SCHEMA_VERSION)
        self.assertGreaterEqual(SNAPSHOT_SCHEMA_VERSION,271)
        for value in(0,'false',None):
            altered=json.loads(json.dumps(saved));entity=next(iter(altered['state']['entities'].values()))
            entity['face_replaced']=value;altered['state_hash']=canonical_hash(altered['state'])
            with self.assertRaises(SnapshotError):Game.from_snapshot(altered,registry())
        for old_schema in (270,SNAPSHOT_SCHEMA_VERSION-1):
            altered=json.loads(json.dumps(saved));altered['schema_version']=old_schema
            with self.assertRaises(SnapshotError):Game.from_snapshot(altered,registry())
        altered=json.loads(json.dumps(saved));next(iter(altered['state']['entities'].values())).pop('face_replaced')
        altered['state_hash']=canonical_hash(altered['state'])
        with self.assertRaises(SnapshotError):Game.from_snapshot(altered,registry())


if __name__=='__main__':unittest.main()
