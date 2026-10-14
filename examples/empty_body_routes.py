"""Synthetic complete empty paid routes, two policies and no invented bodies."""
from dataclasses import replace
import json,sys
from hs_sim.engine import (BodyReference,BodyRootTargetBinding,BodyTargetBinding,
    BodyTargetProfile,CardDefinition,CardType,Game,GrantBattlecry,PlayerSetup,
    Registry,Scenario,TargetMode,TargetSpec,Zone)
from hs_sim.engine.body_grants import RemoveGrantedBody,ConsumeGrantedBody
from hs_sim.engine.effects import (ChoiceOption,Damage,GainArmor,RandomDamage,
    RequestChoice,Summon)
from hs_sim.engine.zones import CardReference,CopyCard,MoveCard

FRIEND=TargetSpec(TargetMode.REQUIRED,(Zone.BOARD,),(CardType.MINION,),'friendly')
ENEMY=replace(FRIEND,relation='enemy')


def registry(mode='normal'):
    r=Registry('empty-body-routes-'+mode)
    for profile in ('paid_a','paid_z'):
        r.register_body_target_profile(BodyTargetProfile(profile,'paid_hand','manual','pre_payment'))
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=100))
    for name in ('friend','enemy','hidden'):
        r.register_card(CardDefinition(name,name,CardType.MINION,attack=1,health=20))
    def root(c):
        effects=[GainArmor(c.player_id,1),Damage(c.target_id,2,c.source_id)]
        if mode=='wait':return [RequestChoice(c.player_id,(ChoiceOption('go','Continue',tuple(effects)),),c.source_id)]
        if mode=='fail':return [RandomDamage((c.state.players[2].hero_id,),1,c.source_id),Summon(c.player_id,'unsupported.empty')]
        if mode=='late':
            return [GrantBattlecry(BodyReference.capture(c.source),'donor',c.source_id),*effects]
        return effects
    r.register_behavior('root',root)
    r.register_behavior('body',lambda c:[GainArmor(c.player_id,3)])
    r.register_card(CardDefinition('unit','Unit',CardType.MINION,cost=2,attack=1,health=20,on_play='root',targeting=FRIEND))
    r.register_card(CardDefinition('plain','Plain',CardType.MINION,cost=1,attack=1,health=20))
    r.register_card(CardDefinition('donor','Donor',CardType.MINION,health=5,battlecry='body',targeting=ENEMY))
    def source(c):
        return next(e for e in c.state.entities.values() if e.card_id=='unit' and e.controller==c.player_id and e.zone==Zone.HAND)
    r.register_behavior('grant',lambda c:[GrantBattlecry(BodyReference.capture(source(c)),'donor',c.source_id)])
    def mutate(c,operation):
        e=source(c);a=next(a for a in e.abilities if a.kind=='battlecry' and a.origin=='granted' and not a.consumed)
        return [operation(BodyReference.capture(e),a.id,'battlecry',c.source_id)]
    r.register_behavior('remove',lambda c:mutate(c,RemoveGrantedBody))
    r.register_behavior('consume',lambda c:mutate(c,ConsumeGrantedBody))
    r.register_behavior('copy',lambda c:[CopyCard(CardReference.capture(source(c)),c.player_id,source_id=c.source_id)])
    r.register_behavior('hide',lambda c:[MoveCard(CardReference.capture(source(c)),c.player_id,Zone.DECK,position='top',source_id=c.source_id)])
    from hs_sim.engine.effects import Draw
    r.register_behavior('draw',lambda c:[Draw(c.player_id,1)])
    for name in ('grant','remove','consume','copy','hide','draw'):
        r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name))
    r.register_body_target_binding(BodyTargetBinding('donor','battlecry','paid_z',('granted',)))
    r.register_body_root_target_binding(BodyRootTargetBinding('unit','paid_a','explicit_root',FRIEND))
    r.register_body_root_target_binding(BodyRootTargetBinding('unit','paid_z','explicit_root',ENEMY))
    r.register_body_root_target_binding(BodyRootTargetBinding('plain','paid_a','body_only'))
    return r


def scenario(*,tools=(),enemy_card='hidden',board=('friend',),enemy_board=('enemy',),plain=False):
    return Scenario((PlayerSetup('hero',hand=('unit',*(('plain',) if plain else ()),*tools),board=board,mana=10,max_mana=10),
        PlayerSetup('hero',hand=(enemy_card,),board=enemy_board,mana=10,max_mana=10)),seed=43)


def ref(game,name,index=0):
    return [c['ref'] for c in game.for_player(1).observe()['observation']['players'][0]['hand'] if c.get('card_id')==name][index]


def command(game,name='unit',*,enemy=True,index=0,position=0):
    port=game.for_player(1);query=port.independent_targets(ref(game,name,index),position=position)
    assert query['error'] is None and query['choices'],query
    observation=port.observe()['observation'];target=observation['players'][1 if enemy else 0]['board'][0]['ref'] if name=='unit' else None
    route=next(c for c in query['choices'] if target in c['root_targets'])
    action={'type':'play_card','card':route['card'],'target':target,'position':position,
        'body_targets':[{'body':b['body'],'target':b['targets'][0]} for b in route['bodies']]}
    if not route['bodies']:action['body_route']=route['body_route']
    return {'revision':query['revision'],'action':action}


def spell_command(game,name):
    return {'revision':game.for_player(1).observe()['revision'],'action':{'type':'play_card','card':ref(game,name)}}


def main():
    mode=sys.argv[1] if len(sys.argv)>1 else 'normal'
    game=Game.from_scenario(scenario(plain=mode=='plain'),registry(mode));initial=game.snapshot();commands=[];positions=[]
    def submit(c):
        result=game.for_player(1).submit(c);assert result['accepted'],result
        commands.append(c);positions.append({'after_commands':len(commands),'snapshot':game.snapshot(),
            'observations':[game.for_player(p).observe() for p in (1,2)]})
    submit(command(game,'plain' if mode=='plain' else 'unit'))
    while game.state.pending_choice:
        legal=game.for_player(1).legal_actions();assert legal['error'] is None
        submit({'revision':legal['revision'],'action':legal['actions'][0]})
    print(json.dumps({'mode':mode,'initial':initial,'commands':commands,'positions':positions,'final':game.snapshot()},ensure_ascii=False))


if __name__=='__main__':main()
