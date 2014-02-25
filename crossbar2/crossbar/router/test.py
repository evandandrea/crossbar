###############################################################################
##
##  Copyright (C) 2014 Tavendo GmbH
##
##  This program is free software: you can redistribute it and/or modify
##  it under the terms of the GNU Affero General Public License, version 3,
##  as published by the Free Software Foundation.
##
##  This program is distributed in the hope that it will be useful,
##  but WITHOUT ANY WARRANTY; without even the implied warranty of
##  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
##  GNU Affero General Public License for more details.
##
##  You should have received a copy of the GNU Affero General Public License
##  along with this program. If not, see <http://www.gnu.org/licenses/>.
##
###############################################################################

import sys
import os
import datetime
import argparse

import psutil

import twisted
from twisted.python import log

from autobahn.twisted.wamp import ApplicationSession
from autobahn.wamp.exception import ApplicationError



from autobahn.wamp.router import RouterFactory
from autobahn.twisted.wamp import RouterSessionFactory
from autobahn.twisted.websocket import WampWebSocketServerFactory
from twisted.internet.endpoints import serverFromString
from twisted.internet import reactor

from autobahn.wamp.protocol import RouterApplicationSession




class RouterTransport:
   def __init__(self, id, config, port):
      self.id = id
      self.config = config
      self.port = port


class RouterClass:
   def __init__(self, id, klassname, realm):
      self.id = id
      self.klassname = klassname
      self.realm = realm



class RouterModule:
   """
   Entities:
      - Realms
      - Transports
      - Links
      - Classes
   """

   def __init__(self, session, pid):
      self._session = session
      self._pid = pid

      self.debug = self._session.factory.options.debug
      self.verbose = self._session.factory.options.verbose

      self._component_sessions = {}
      self._component_no = 0

      self._router_factory = None
      self._router_session_factory = None
      self._router_transports = {}
      self._router_transport_no = 0

      session.register(self.start,           'crossbar.node.module.{}.router.start'.format(pid))
      session.register(self.stop,            'crossbar.node.module.{}.router.stop'.format(pid))

      session.register(self.startClass,      'crossbar.node.module.{}.router.start_class'.format(pid))
      session.register(self.stopClass,       'crossbar.node.module.{}.router.stop_class'.format(pid))

      session.register(self.startRealm,      'crossbar.node.module.{}.router.start_realm'.format(pid))
      #session.register(self.stopRealm,       'crossbar.node.module.{}.router.stop_realm'.format(pid))

      session.register(self.startTransport,  'crossbar.node.module.{}.router.start_transport'.format(pid))
      session.register(self.stopTransport,   'crossbar.node.module.{}.router.stop_transport'.format(pid))
      session.register(self.listTransports,  'crossbar.node.module.{}.router.list_transports'.format(pid))

      session.register(self.startLink,       'crossbar.node.module.{}.router.start_link'.format(pid))
      session.register(self.stopLink,        'crossbar.node.module.{}.router.stop_link'.format(pid))


   def start(self, config):
      if not self._router_factory:
         print "Starting router module", self._pid, config
         self._router_factory = RouterFactory()
         self._router_session_factory = RouterSessionFactory(self._router_factory)
      else:
         raise ApplicationError("crossbar.error.module_already_started")


   def stop(self):
      print "Stopping router module", self._pid


   def startRealm(self, name, config):
      print "Realm started", config



   def listClasses(self):
      """
      List currently running application components.
      """
      return sorted(self._component_sessions.keys())


   def startClass(self, klassname, realm):
      """
      Dynamically start an application component to run next to the router in "embedded mode".
      """

      ## dynamically load the application component ..
      ##
      try:
         log.msg("Node process {}: starting class '{}' in realm '{}' ..".format(self._pid, klassname, realm))

         import importlib
         c = klassname.split('.')
         mod, klass = '.'.join(c[:-1]), c[-1]
         app = importlib.import_module(mod)
         SessionKlass = getattr(app, klass)

      except Exception as e:
         log.msg("Node process {}: failed to import class - {}".format(e))
         raise ApplicationError("crossbar.error.class_import_failed", str(e))

      else:
         ## .. and create and add an WAMP application session to
         ## run the component next to the router
         ##
         comp = SessionKlass(realm)
         self._router_session_factory.add(comp)
         
         self._component_no += 1
         self._component_sessions[self._component_no] = comp
         return self._component_no


   def stopClass(self, id):
      """
      Stop a application component on this router.
      """
      if id in self._component_sessions:
         log.msg("Node process {}: stopping component {}".format(self._pid, id))

         try:
            #self._component_sessions[id].disconnect()
            self._router_session_factory.remove(self._component_sessions[id])
            del self._component_sessions[id]
         except Exception as e:
            raise ApplicationError("crossbar.error.component.cannot_stop", "Failed to stop component {}: {}".format(id, e))
      else:
         raise ApplicationError("crossbar.error.no_such_component", "No component {}".format(id))


   def listTransports(self):
      """
      List currently running transports.
      """
      return sorted(self._router_transports.keys())


   def startTransport(self, config):
      """
      Start a transport on this router module.
      """
      log.msg("Node process {}: starting transport on router module.".format(self._pid))

      self._router_transport_no += 1

      if config['type'] == 'websocket':
         transport_factory = WampWebSocketServerFactory(self._router_session_factory, config['url'], debug = False)
         transport_factory.setProtocolOptions(failByDrop = False)

         id = self._router_transport_no

         # IListeningPort or an CannotListenError
         server = serverFromString(reactor, str(config['endpoint']))
         d = server.listen(transport_factory)

         def ok(port):
            self._router_transports[id] = RouterTransport(id, config, port)
            return id

         def fail(err):
            raise ApplicationError("crossbar.error.cannotlisten", str(err.value))

         d.addCallbacks(ok, fail)
         return d
      else:
         raise ApplicationError("crossbar.error.invalid_transport", "Unknown transport type '{}'".format(config['type']))



   def stopTransport(self, id):
      """
      Stop a transport on this router module.
      """
      if id in self._router_transports:
         log.msg("Node process {}: stopping transport {}".format(self._pid, id))

         try:
            d = self._router_transports[id].port.stopListening()

            def ok(_):
               del self._router_transports[id]

            def fail(err):
               raise ApplicationError("crossbar.error.transport.cannot_stop", "Failed to stop transport {}: {}".format(id, str(err.value)))

            d.addCallbacks(ok, fail)
            return d

         except Exception as e:
            raise ApplicationError("crossbar.error.transport.cannot_stop", "Failed to stop transport {}: {}".format(id, e))
      else:
         raise ApplicationError("crossbar.error.no_such_transport", "No transport {}".format(id))



   def listLinks(self):
      """
      List currently running links.
      """
      return []


   def startLink(self, config):
      """
      Start a link on this router.
      """
      print "Starting router link", self._pid, config


   def stopLink(self, id):
      """
      Stop a link on this router.
      """
      print "Stopping router link", self._pid, id




class NodeProcess(ApplicationSession):

   def onConnect(self):
      log.msg("Connected to node.")
      self._component = None
      self.join("crossbar")


   def onJoin(self, details):
      log.msg("Realm joined.")

      pid = os.getpid()

      def get_cpu_affinity():
         p = psutil.Process(os.getpid())
         return p.get_cpu_affinity()

      self.register(get_cpu_affinity, 'crossbar.node.component.{}.get_cpu_affinity'.format(pid))


      def set_cpu_affinity(cpus):
         p = psutil.Process(os.getpid())
         p.set_cpu_affinity(cpus)

      self.register(set_cpu_affinity, 'crossbar.node.component.{}.set_cpu_affinity'.format(pid))


      def utcnow():
         now = datetime.datetime.utcnow()
         return now.strftime("%Y-%m-%dT%H:%M:%SZ")

      self.register(utcnow, 'crossbar.node.component.{}.now'.format(pid))


      def get_classpaths():
         return sys.path

      self.register(get_classpaths, 'crossbar.node.component.{}.get_classpaths'.format(pid))


      def add_classpaths(paths, prepend = True):
         sys.path = paths + sys.path

      self.register(add_classpaths, 'crossbar.node.component.{}.add_classpaths'.format(pid))


      def start_component(config):
         ## create a WAMP router factory
         ##
         log.msg("Starting component")
         log.msg(config)

         try:

            from autobahn.wamp.router import RouterFactory
            router_factory = RouterFactory()

            ## create a WAMP router session factory
            ##
            from autobahn.twisted.wamp import RouterSessionFactory
            session_factory = RouterSessionFactory(router_factory)

            ## create a WAMP-over-WebSocket transport server factory
            ##
            from autobahn.twisted.websocket import WampWebSocketServerFactory
            transport_factory = WampWebSocketServerFactory(session_factory, config['url'], debug = False)
            transport_factory.setProtocolOptions(failByDrop = False)

            if True:
               ## start the WebSocket server from an endpoint
               ##
               from twisted.internet.endpoints import serverFromString
               from twisted.internet import reactor
               server = serverFromString(reactor, str(config['endpoint']))

               # IListeningPort or an CannotListenError
               d = server.listen(transport_factory)

               def ok(port):
                  return "Ok, listening"

               def fail(err):
                  raise ApplicationError("crossbar.error.cannotlisten", str(err.value))

               d.addCallbacks(ok, fail)
               return d

            else:
               # http://stackoverflow.com/questions/12542700/setsockopt-before-connect-for-reactor-connecttcp
               # http://twistedmatrix.com/documents/current/api/twisted.internet.interfaces.IReactorSocket.html
               # http://stackoverflow.com/questions/10077745/twistedweb-on-multicore-multiprocessor

               ## start the WebSocket server from a custom port that share TCP ports
               ##
               p = CustomPort(9000, transport_factory, reuse = True)
               try:
                  p.startListening()
               except twisted.internet.error.CannotListenError as e:
                  raise ApplicationError("crossbar.error.cannotlisten", str(e))
               else:
                  return "Ok, listening"


         except Exception as e:
            log.msg("Fuck {}".format(e))

         log.msg("Router started")


      self.register(start_component, 'crossbar.node.component.{}.start'.format(pid))


      self._routerModule = RouterModule(self, pid)
      #self.register(start_component, 'crossbar.node.component.{}.start'.format(pid))


      log.msg("Procedures registered.")

      self.publish('crossbar.node.component.on_start', {'pid': os.getpid(), 'cmd': [sys.executable] + sys.argv})




def run(Component):


   ## create the top-level parser
   ##
   parser = argparse.ArgumentParser(prog = 'crossbar',
                                    description = "Crossbar.io polyglot application router")

   ## top-level options
   ##
   parser.add_argument('-d',
                       '--debug',
                       action = 'store_true',
                       help = 'Debug on.')

   parser.add_argument('-v',
                       '--verbose',
                       action = 'store_true',
                       help = 'Verbose (human) output on.')

   parser.add_argument('--reactor',
                       default = None,
                       choices = ['select', 'poll', 'epoll', 'kqueue', 'iocp'],
                       help = 'Explicit Twisted reactor selection')

   ## parse cmd line args
   ##
   options = parser.parse_args()


   ## make sure logging to something else than stdio
   ## is setup _first_
   log.startLogging(sys.stderr)
   #log.startLogging(open('test.log', 'w'))


   ## we use an Autobahn utility to import the "best" available Twisted reactor
   ##
   from autobahn.twisted.choosereactor import install_reactor
   reactor = install_reactor(options.reactor, options.verbose)

   ##
   from twisted.python.reflect import qual
   log.msg("Node process {}: starting Python component on {} ..".format(os.getpid(), qual(reactor.__class__).split('.')[-1]))

   try:

      ## create a WAMP application session factory
      ##
      from autobahn.twisted.wamp import ApplicationSessionFactory
      session_factory = ApplicationSessionFactory()
      session_factory.options = options
      session_factory.session = Component

      ## create a WAMP-over-WebSocket transport server factory
      ##
      from autobahn.twisted.websocket import WampWebSocketServerFactory
      transport_factory = WampWebSocketServerFactory(session_factory, "ws://localhost", debug = False)
      transport_factory.setProtocolOptions(failByDrop = False)

      ## create a protocol instance and wire up to stdio
      ##
      from twisted.internet import stdio
      proto = transport_factory.buildProtocol(None)
      stdio.StandardIO(proto)

      ## now start reactor loop
      ##
      if options.verbose:
         log.msg("Node process {}: starting reactor".format(os.getpid()))
      reactor.run()

   except Exception as e:
      log.msg("Node process {}: unhandled exception - {}".format(os.getpid(), e))
      sys.exit(1)



if __name__ == '__main__':
   run(NodeProcess)