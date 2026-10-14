"""Original board references share stored creation, cost, capacity and knowledge."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition,CardType,CostSpec,EndTurn,Game,IllegalAction,Keyword,
    PlayCard,PlayerSetup,Registry,ResolutionError,Scenario,SelectChoice,SummonStats,
    TargetMode,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,Damage,Destroy,
    Draw,Freeze,GainArmor,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.zones import CardReference,CopyCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

CARD='OG_291'
PIN='69d9992a35dbad506ad7286357afbb4edecb511216c052a4936d709e13b7a459'
FIXED=SummonStats(1,1)
ONE=CostSpec(set_to=1,minimum=0,card_types=(CardType.MINION,))


def evidence():
    data=json.loads((Path(__file__).resolve().parents[1]/'data/support/board-to-stored-copy-basics.json').read_bytes())
    if canonical_digest(data)!=PIN:raise ValueError('Board-to-stored evidence changed')
    for row in data['records']:
        if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Full raw copy row changed')
    return data


def registry():
    r=Registry('isolated-board-to-stored-copy-v1')
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=80,metadata=metadata(tribes=())))
    r.register_behavior('cry',lambda c:(GainArmor(c.player_id,5),))
    r.register_card(CardDefinition('body','Body',CardType.MINION,cost=6,attack=4,health=7,
        keywords=(Keyword.TAUNT,),battlecry='cry',metadata=metadata(tribes=())))
    r.register_card(CardDefinition('plain','Plain',CardType.MINION,cost=2,attack=2,health=4,metadata=metadata(tribes=())))
    def copy(c,*,destination=Zone.HAND,position='random',mode='current',stats=None,cost=None,player=1,expires=None):
        return CopyCard(MinionReference.capture(c.state.entities[c.target_id]),player,destination,mode,position,c.source_id,stats,cost,expires)
    raw=evidence()['records'][0]['data']
    r.register_behavior('shadow',lambda c:() if c.target_id is None else (copy(c,stats=FIXED,cost=ONE),))
    r.register_card(CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        battlecry='shadow',targeting=TargetSpec(TargetMode.IF_AVAILABLE,kinds=(CardType.MINION,),relation='friendly'),metadata=metadata_from_record(raw)))
    def choice(c):
        effect=copy(c,stats=FIXED,cost=ONE)
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Copy',(effect,)),
            ChoiceOption('fault','Copy and fail',(effect,InvokeBehavior('late-fault',c.source_id,c.player_id))),
        ),c.source_id),)
    scripts={
        'copy':lambda c:(copy(c),),
        'fixed':lambda c:(copy(c,stats=FIXED,cost=ONE),),
        'full-copy':lambda c:(AddToHand(1,'plain'),copy(c,stats=FIXED,cost=ONE)),
        'base':lambda c:(copy(c,mode='base'),),
        'opponent':lambda c:(copy(c,player=2,stats=FIXED,cost=ONE),),
        'top':lambda c:(copy(c,destination=Zone.DECK,position='top',stats=FIXED,cost=ONE),),
        'bottom':lambda c:(copy(c,destination=Zone.DECK,position='bottom'),),
        'random':lambda c:(copy(c,destination=Zone.DECK),),
        'bad-position':lambda c:(copy(c,destination=Zone.DECK,position=99),),
        'prep':lambda c:(Buff(c.target_id,3,2,c.source_id),Damage(c.target_id,3,c.source_id),Freeze(c.target_id)),
        'silence-source':lambda c:(Silence(c.target_id),),
        'draw':lambda c:(Draw(1,1),),
        'wait':choice,
        'fault':lambda c:(copy(c,stats=FIXED,cost=ONE),InvokeBehavior('late-fault',c.source_id,c.player_id)),
        'expired':lambda c:(copy(c,cost=ONE,expires=1),),
        'temporary':lambda c:(copy(c,cost=ONE,expires=c.state.turn),),
    }
    for key,body in scripts.items():
        r.register_behavior(key,body);r.register_card(CardDefinition(key,key,CardType.SPELL,on_play=key,
            targeting=TargetSpec(kinds=(CardType.MINION,)),metadata=metadata(tribes=())))
    for key,change in (
        ('stale-destroy',lambda c:Destroy(c.target_id,c.source_id)),
        ('stale-transform',lambda c:Transform(c.target_id,'plain')),
        ('stale-control',lambda c:ChangeControl(c.target_id,2)),
        ('stale-return',lambda c:ReturnToHand(c.target_id)),
        ('stale-sleep',lambda c:MakeDormant(c.target_id,None)),
    ):
        def body(c,change=change):
            effect=copy(c,stats=FIXED,cost=ONE)
            return (change(c),effect)
        r.register_behavior(key,body);r.register_card(CardDefinition(key,key,CardType.SPELL,on_play=key,
            targeting=TargetSpec(kinds=(CardType.MINION,)),metadata=metadata(tribes=())))
    r.register_behavior('stored-copy',lambda c:(CopyCard(CardReference.capture(next(c.state.entities[i]
        for i in c.state.players[1].hand if c.state.entities[i].card_id=='body')),1),))
    r.register_card(CardDefinition('stored-copy','Stored copy',CardType.SPELL,on_play='stored-copy',metadata=metadata(tribes=())))
    r.register_behavior('late-fault',lambda c:(AddToHand(1,'unknown.board-stored'),))
    def observe(c):
        entity=c.state.entities[c.event.target_id]
        if entity.card_id!='body':return ()
        return (GainArmor(2,entity.attack*100+entity.health*10+entity.cost),)
    r.register_behavior('observe',observe)
    r.register_card(CardDefinition('observer','Creation observer',CardType.MINION,health=3,
        triggers=(TriggerSpec('card_created','observe'),),metadata=metadata(tribes=())))
    return r


class BoardToStoredCopyBasicsTests(unittest.TestCase):
    def game(self,hand=(),*,board=('body',),enemy=(),enemy_hand=(),cap=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=('plain',)*3,mana=10,max_mana=10,hand_cap=cap),
            PlayerSetup('hero',hand=enemy_hand,board=enemy,deck=('plain',)*3,mana=10,max_mana=10)),seed=67),registry())
    def source(self,g,p=1):return next(i for i in g.state.players[p].board if g.state.entities[i].card_id=='body')
    def play(self,g,name,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)
        return g.apply(PlayCard(1,eid,target))
    def copied(self,g,p=1,zone=Zone.HAND):
        return next(g.state.entities[i] for i in reversed(getattr(g.state.players[p],zone.value))
            if g.state.entities[i].card_id=='body' and g.state.entities[i].origin_entity_id is not None)
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;return g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));h=Game.from_snapshot(saved,registry())
        self.assertEqual(h.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return h
    def values(self,e,attack,health,cost,damage=0):self.assertEqual((e.attack,e.max_health,e.cost,e.damage),(attack,health,cost,damage))

    def test_full_raw_pin_and_only_necessary_shadowcaster(self):
        data=evidence();card=registry().card(CARD)
        self.assertEqual(data['new_real_card_adapters'],[CARD]);self.assertEqual((card.cost,card.attack,card.health),(5,4,4))
        self.assertEqual(card.metadata.classes,('rogue',));self.assertEqual(card.targeting.relation,'friendly')

    def test_original_reference_types_and_typed_overrides(self):
        g=self.game();ref=MinionReference.capture(g.state.entities[self.source(g)])
        self.assertEqual(CopyCard(ref,1,stats=FIXED,cost=ONE).card,ref)
        self.assertIsNone(CopyCard(ref,1).stats)
        with self.assertRaises(ValueError):CardReference.capture(g.state.entities[self.source(g)])
        for fields in ({'destination':Zone.BOARD},{'stats':{'attack':1,'health':1}},{'cost':1},{'cost':None,'expires_turn':1}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):CopyCard(ref,1,**fields)

    def test_real_battlecry_creates_fixed_one_cost_copy_and_keeps_source(self):
        g=self.game((CARD,));source=self.source(g);self.play(g,CARD,source);e=self.copied(g)
        self.values(e,1,1,1);self.assertEqual((e.owner,e.controller,e.zone),(1,1,Zone.HAND))
        self.assertEqual(e.origin_entity_id,source);self.assertNotEqual(e.id,source)
        self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.assertEqual(g.state.players[1].mana,5)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0);self.portable(g)

    def test_real_optional_and_enemy_target_rejection(self):
        g=self.game((CARD,),board=(),enemy=('body',));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,CARD,self.source(g,2))
        self.assertEqual(g.snapshot(),before);self.play(g,CARD)
        self.assertFalse(any(g.state.entities[i].origin_entity_id for i in g.state.players[1].hand));self.portable(g)

    def test_current_material_keeps_local_buffs_and_abilities_but_not_battlefield_status(self):
        g=self.game(('prep','copy'));source=self.source(g);self.play(g,'prep',source);self.play(g,'copy',source)
        e=self.copied(g);self.values(e,7,9,6);self.assertIn(Keyword.TAUNT,e.keywords)
        self.assertFalse(e.frozen);self.assertEqual(e.attacks_this_turn,0);self.values(g.state.entities[source],7,9,6,3)
        self.assertTrue(g.state.entities[source].frozen);self.portable(g)

    def test_base_material_rebuilds_printed_card_without_source_enchantments(self):
        g=self.game(('prep','base'));source=self.source(g);self.play(g,'prep',source);self.play(g,'base',source)
        e=self.copied(g);self.values(e,4,7,6);self.assertEqual(e.enchantments,[]);self.assertIn(Keyword.TAUNT,e.keywords);self.portable(g)

    def test_fixed_copy_overrides_after_local_layers_and_before_creation_observer(self):
        g=self.game(('prep','fixed'),board=('body','observer'));source=self.source(g)
        self.play(g,'prep',source);self.play(g,'fixed',source);self.values(self.copied(g),1,1,1)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,111);self.portable(g)

    def test_enemy_board_source_and_different_recipient_get_independent_owner(self):
        g=self.game(('fixed',),board=(),enemy=('body',));source=self.source(g,2);self.play(g,'fixed',source)
        e=self.copied(g);self.assertEqual((e.owner,e.controller,e.origin_entity_id),(1,1,source));self.values(e,1,1,1);self.portable(g)
        g=self.game(('opponent',));source=self.source(g);self.play(g,'opponent',source)
        e=self.copied(g,2);self.assertEqual((e.owner,e.controller,e.origin_entity_id),(2,2,source));self.portable(g)

    def test_top_deck_copy_is_installed_before_draw_and_keeps_physical_identity(self):
        g=self.game(('top','draw'));source=self.source(g);self.play(g,'top',source);e=self.copied(g,zone=Zone.DECK)
        self.assertEqual(g.state.players[1].deck[0],e.id);self.values(e,1,1,1)
        self.play(g,'draw',source);self.assertEqual(g.state.entities[e.id].zone,Zone.HAND);self.values(g.state.entities[e.id],1,1,1);self.portable(g)

    def test_bottom_and_random_deck_insertion_reuse_original_rng(self):
        g=self.game(('bottom',));before=g.snapshot()['rng_state'];self.play(g,'bottom',self.source(g));e=self.copied(g,zone=Zone.DECK)
        self.assertEqual(g.state.players[1].deck[-1],e.id);self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)
        g=self.game(('random',));before=g.snapshot()['rng_state'];self.play(g,'random',self.source(g))
        self.assertNotEqual(g.snapshot()['rng_state'],before);self.portable(g)

    def test_invalid_insertion_and_expired_cost_roll_back_without_allocations(self):
        g=self.game(('bad-position',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad-position',self.source(g))
        self.assertEqual(g.snapshot(),before)
        g=self.game(('expired',));g.apply(EndTurn(1));g.apply(EndTurn(2));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'expired',self.source(g))
        self.assertEqual(g.snapshot(),before)

    def test_per_player_capacity_and_burned_copy_do_not_destroy_source(self):
        for cap,zone in ((2,Zone.GRAVEYARD),(3,Zone.HAND)):
            with self.subTest(cap=cap):
                g=self.game(('full-copy','plain'),cap=cap);source=self.source(g);self.play(g,'full-copy',source)
                e=self.copied(g,zone=zone);self.values(e,1,1,1)
                self.assertEqual(g.state.entities[source].zone,Zone.BOARD)
                self.assertFalse(any(d.entity_id==source for d in g.state.death_history));self.portable(g)

    def test_default_stored_reference_copy_is_still_supported(self):
        g=self.game(('body','stored-copy'));self.play(g,'stored-copy')
        hand=[g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id=='body']
        self.assertEqual(len(hand),2);self.assertNotEqual(hand[0].id,hand[1].id);self.values(hand[1],4,7,6);self.portable(g)

    def test_stale_original_reference_skips_destruction_face_control_return_and_dormancy(self):
        for name in ('stale-destroy','stale-transform','stale-control','stale-return','stale-sleep'):
            with self.subTest(name=name):
                g=self.game((name,));self.play(g,name,self.source(g))
                self.assertFalse(any(g.state.entities[i].origin_entity_id for i in g.state.players[1].hand))
                self.assertTrue(any(e.kind=='zone_target_skipped' for e in g.events));self.portable(g)

    def test_source_silence_is_current_material_and_copy_does_not_restore_printed_keywords(self):
        g=self.game(('silence-source','copy'));source=self.source(g);self.play(g,'silence-source',source);self.play(g,'copy',source)
        self.assertNotIn(Keyword.TAUNT,self.copied(g).keywords);self.assertTrue(self.copied(g).silenced);self.portable(g)

    def test_fixed_copy_remains_one_cost_when_played_and_uses_original_battlecry(self):
        g=self.game(('fixed',));source=self.source(g);self.play(g,'fixed',source);e=self.copied(g);before=g.state.players[1].mana
        g.apply(PlayCard(1,e.id));self.assertEqual(g.state.players[1].mana,before-1);self.values(g.state.entities[e.id],1,1,1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,5);self.portable(g)

    def test_temporary_cost_uses_existing_global_expiry_without_changing_copy_stats(self):
        g=self.game(('temporary',));self.play(g,'temporary',self.source(g));e=self.copied(g);self.assertEqual(e.cost,1)
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[e.id].cost,6);self.portable(g)

    def test_waiting_effect_codec_clone_replay_and_successful_resumption(self):
        g=self.game(('wait',));self.play(g,'wait',self.source(g));restored=self.portable(g)
        self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot());self.values(self.copied(g),1,1,1);self.portable(g)

    def test_immediate_and_waiting_late_errors_restore_original_transactions(self):
        g=self.game(('fault',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'fault',self.source(g))
        self.assertEqual(g.snapshot(),before)
        g=self.game(('wait',));self.play(g,'wait',self.source(g));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.portable(g)

    def test_reference_and_overrides_round_trip_without_public_private_state(self):
        g=self.game();ref=MinionReference.capture(g.state.entities[self.source(g)]);effect=CopyCard(ref,1,stats=FIXED,cost=ONE)
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state);self.assertEqual(codec.decode(codec.encode(effect)),effect)
        for player in (1,2):
            visible=json.dumps(g.observe(player))+json.dumps(g.for_player(player).legal_actions())
            for key in ('MinionReference','resolution_frame','CopyEntryMaterial','zone_epoch','set_cost'):
                self.assertNotIn('"'+key+'"',visible)
