Introduction.
==================================

Twoost was created during development of production code in `Wargamin.net`.
Actually its core parts are just a generalization of some modules from live system.

The main aim for Twoost is a standarization & speeding
up of develoment process on the initial dev stages.
So, new developers can start writing code quickly.
And they shouldn't think about a lot of boring stuff, like how to
configure your app, or how to place python files, or how to start workers.
Invention of wheels is a bad idea.

Twoost provids the following:
 - proposed structure for your twisted-app (but you are free to change it);
 - a lot of best practices, borned from expierence;
 - powerfull init scripts;
 - simple configuration micsosystem;
 - bunch of default settings (like logging);
 - ready to use services for work with AMQP, HTTP, SQL, Memcaded;
 - utilities to simplify usage of twisted web (dumb routing, authhmac etc);
 - smart one-connection servcie with reconnecting & heartbeating support;
 - some handy dev tools, like healthcheck or manhole;
 - and more...

Almost all parts of Twoost are independed from each other.
For example, you can use only AMQP client or Web tools if you wish.
But all Twoost parts are created to be accurately integrated.
So I recommend to use the whole Twoost at the starting point of develoment.
And then maybe to adopt and tune some parts of it.

Twoost are open for contributions and improvements.
Fell free to fork an experiment with it.
Feel free to add new features.
And don't forget to create pull requests & bug reports at github :)
