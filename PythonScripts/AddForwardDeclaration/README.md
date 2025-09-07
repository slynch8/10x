
# AddForwardDeclaration
This script will automatically add a forward declaration named after the token the cursor is currently over.

For example, given this code:

```
#pragma once

/**
 * 
 */
class Test
{
protected: 
    NeedForwardDecl* yo;
};
```

if you place the cursor somewhere inside the `NeedForwardDecl` token and execute the AddForwardDeclation script via a key bind, the result will be:

```
#pragma once
class NeedForwardDecl;

/**
 * 
 */
class Test
{
protected: 
    NeedForwardDecl* yo;
};
```