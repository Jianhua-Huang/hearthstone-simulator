"""The existing bounded Draw primitive can express a frozen hand-count gap."""
from pathlib import Path
import json
import unittest

from hs_sim.engine import (Attack, CardDefinition, CardType, CastWhenDrawnSpec, EndTurn,
    Game, Keyword, PlayCard, PlayerSetup, Registry, ResolutionError, Scenario,
    SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Draw, InvokeBehavior, ModifyWeapon, RequestChoice)
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

CARD='REV_509'
PIN='9a345a5deca3c78c05cf2a748f5d87b587415c01448587f986477c86969c559f'


def evidence():
    value=json.loads((Path(__file__).resolve().parents[1]/'data/support/fixed-hand-threshold-draw-basics.json').read_bytes())
    if canonical_digest(value)!=PIN:raise ValueError('Complete threshold draw evidence changed')
    for row in value['records']:
        if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Raw threshold draw card changed')
    return value


def registry():
    r=Registry('isolated-fixed-hand-gap-draw-v1')
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=80,metadata=metadata(tribes=())))
    r.register_card(CardDefinition('plain','Plain card',CardType.MINION,attack=1,health=5,metadata=metadata(tribes=())))
    def draw_to_three(c):
        if c.event.source_id!=c.state.players[c.player_id].hero_id:return ()
        return (Draw(c.player_id,max(0,3-len(c.state.players[c.player_id].hand)),c.source_id),)
    r.register_behavior('draw-to-three',draw_to_three)
    raw=evidence()['records'][0]['data']
    r.register_card(CardDefinition(CARD,raw['name'],CardType.WEAPON,cost=raw['cost'],attack=raw['attack'],
        durability=raw['health'],triggers=(TriggerSpec('attack_finished','draw-to-three'),),metadata=metadata_from_record(raw)))
    r.register_behavior('wear',lambda c:(ModifyWeapon(c.state.players[c.player_id].weapon_id,durability=-1,source_id=c.source_id),))
    r.register_card(CardDefinition('wear','One remaining durability',CardType.SPELL,on_play='wear',metadata=metadata(tribes=())))
    r.register_behavior('prompt',lambda c:(RequestChoice(c.player_id,(
        ChoiceOption('ok','Continue',()),
        ChoiceOption('fault','Fail', (InvokeBehavior('late-fault',c.source_id,c.player_id),)),
    ),c.source_id),))
    r.register_behavior('late-fault',lambda c:(AddToHand(c.player_id,'unknown.threshold-draw'),))
    r.register_card(CardDefinition('prompt','Draw lifecycle pause',CardType.SPELL,on_play='prompt',
        keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec(choices='player'),metadata=metadata(tribes=())))
    return r


class FixedHandThresholdDrawBasicsTests(unittest.TestCase):
    def game(self,hand=(),deck=('plain',)*5,*,weapon=CARD,enemy_weapon=None,enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,deck=deck,weapon_card_id=weapon,mana=10,max_mana=10),
            PlayerSetup('hero',hand=enemy_hand,deck=('plain',)*5,weapon_card_id=enemy_weapon,mana=10,max_mana=10),
        ),seed=41),registry())
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def attack(self,g,p=1):return g.apply(Attack(p,self.hero(g,p).id,self.hero(g,3-p).id))
    def cast(self,g,name):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)
        return g.apply(PlayCard(1,eid))
    def choose(self,g,name):
        choice=g.state.pending_choice;return g.apply(SelectChoice(choice.player_id,choice.id,(name,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));restored=Game.from_snapshot(saved,registry())
        self.assertEqual(restored.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return restored

    def test_full_raw_and_one_necessary_native_adapter(self):
        data=evidence();card=registry().card(CARD)
        self.assertEqual(data['new_real_card_adapters'],[CARD])
        self.assertEqual([r['id'] for r in data['records']],[CARD,'CORE_REV_509'])
        self.assertEqual((card.cost,card.attack,card.durability,card.metadata.classes),(3,3,2,('demon_hunter',)))

    def test_initial_hand_gap_is_bounded_and_each_draw_keeps_weapon_source(self):
        for size in range(5):
            with self.subTest(size=size):
                g=self.game(('plain',)*size);wid=g.state.players[1].weapon_id;self.attack(g)
                self.assertEqual(len(g.state.players[1].hand),max(3,size))
                self.assertEqual(len(g.state.draw_history),max(0,3-size))
                self.assertTrue(all(r.source_id==wid and r.player_id==1 for r in g.state.draw_history))
                self.assertEqual(g.state.entities[wid].durability,1);self.portable(g)

    def test_empty_or_short_deck_uses_only_original_missing_draw_attempts(self):
        for cards,damage in ((0,6),(1,3),(2,1)):
            with self.subTest(cards=cards):
                g=self.game(deck=('plain',)*cards);self.attack(g)
                self.assertEqual(len(g.state.draw_history),3)
                self.assertEqual(len(g.state.players[1].hand),cards)
                self.assertEqual(self.hero(g).damage,damage)
                self.assertEqual(g.state.players[1].fatigue,3-cards)
                self.portable(g)

    def test_already_full_threshold_does_not_consume_rng_or_create_draw_roots(self):
        g=self.game(('plain',)*3);before=g.snapshot()['rng_state'];self.attack(g)
        self.assertEqual(g.snapshot()['rng_state'],before);self.assertEqual(g.state.draw_history,[])
        self.assertEqual(self.hero(g).attacks_this_turn,1);self.portable(g)

    def test_last_durability_still_delivers_original_captured_weapon_body(self):
        g=self.game(('wear',));wid=g.state.players[1].weapon_id;self.cast(g,'wear');self.attack(g)
        self.assertIsNone(g.state.players[1].weapon_id);self.assertEqual(g.state.entities[wid].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].hand),3)
        self.assertEqual(len(g.state.draw_history),3)
        self.assertTrue(all(r.source_id==wid for r in g.state.draw_history));self.portable(g)

    def test_physical_weapon_play_uses_original_payment_and_post_play_hand_count(self):
        g=self.game((CARD,'plain'),weapon=None);self.cast(g,CARD);self.attack(g)
        self.assertEqual(g.state.players[1].mana,7);self.assertEqual(len(g.state.players[1].hand),3)
        self.assertEqual(len(g.state.draw_history),2);self.portable(g)

    def test_other_player_attack_draws_only_for_its_captured_weapon_owner(self):
        g=self.game(('plain',),enemy_weapon=CARD,enemy_hand=('plain',))
        g.apply(EndTurn(1));start=len(g.state.draw_history);self.attack(g,2)
        self.assertEqual(len(g.state.players[1].hand),1);self.assertEqual(len(g.state.players[2].hand),3)
        self.assertEqual([r.player_id for r in g.state.draw_history[start:]],[2]);self.portable(g)

    def test_last_weapon_waiting_draw_chain_restores_replays_and_rolls_back_failed_choice(self):
        g=self.game(('wear',),deck=('prompt','plain','plain','plain'));self.cast(g,'wear');self.attack(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertIsNone(g.state.players[1].weapon_id)
        restored=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)
        for branch in (g,restored):
            self.choose(branch,'ok');self.assertEqual(len(branch.state.players[1].hand),3)
            self.assertEqual([r.outcome for r in branch.state.draw_history],['cast','hand','hand','hand'])
            self.portable(branch)
        self.assertEqual(g.snapshot(),restored.snapshot())

    def test_player_interfaces_hide_full_draw_records_and_work_frames(self):
        g=self.game();self.attack(g);before=g.snapshot()
        for p in (1,2):
            public=json.dumps(g.observe(p))+json.dumps(g.for_player(p).legal_actions())
            for key in ('draw_history','resolution_frame','replacement_id','source_sha256'):
                self.assertNotIn('"'+key+'"',public)
        self.assertEqual(g.snapshot(),before)
